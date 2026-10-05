"""Consistent local backups and guarded restores of prepared company deployments.

Restore keeps the replaced runtime directories in a quarantine directory. Credentials
stay in the deployment .env and must be retained separately with the same signing key.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.company_compose import compose_environment

RUNTIME = ('alarm_db', 'data')


def contained(root: Path, path: Path) -> Path:
    root = root.resolve()
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError('Path must remain strictly inside the deployment directory')
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Runtime paths must not contain symbolic links or junctions')
    return resolved


def hashes(directory: Path) -> dict[str, str]:
    result = {}
    for path in sorted(directory.rglob('*')):
        contained(directory, path)
        if path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            result[path.relative_to(directory).as_posix()] = digest.hexdigest()
    return result


class Deployment:
    def __init__(self, directory: Path):
        self.root = directory.resolve()
        self.manifest = json.loads((self.root / 'deployment.json').read_text(encoding='utf-8'))
        m = self.manifest
        if (Path(m['directory']).resolve() != self.root or not m.get('fresh_runtime')
                or m['data_store'] != 'postgresql' or not re.fullmatch(r'[a-z][a-z0-9-]{2,40}', m['project'])
                or any(not re.fullmatch(r'[a-z_][a-z0-9_]*', m[k]) for k in ('database', 'database_user'))):
            raise ValueError('Invalid prepared deployment manifest')
        self.project = m['project']
        self.base = f"http://127.0.0.1:{int(m['port'])}"
        self.pg = self.project + '-postgres-1'

    def compose(self, *args: str):
        config = self.root / 'compose.company.json'
        return subprocess.run(['docker', 'compose', '--env-file', str(self.root / '.env'),
                               '--project-name', self.project, '-f', str(config), *args],
                              env=compose_environment(config.read_text(encoding='utf-8')),
                              check=True, capture_output=True)

    def validate_mounts(self) -> dict:
        containers = json.loads(subprocess.check_output(['docker', 'inspect', *[
            self.project + '-' + name + '-1' for name in ('alarm_rag', 'postgres', 'qdrant')]], timeout=30))
        result = {}
        expected = {'alarm_rag': {'/app/' + n: n for n in ('alarm_db', 'data', 'backups')},
                    'postgres': {'/var/lib/postgresql/data': 'postgres_data'}, 'qdrant': {}}
        for container in containers:
            labels = container['Config']['Labels']
            if labels['com.docker.compose.project'] != self.project:
                raise ValueError('Container ownership mismatch')
            service = labels['com.docker.compose.service']
            mounts = {mount['Destination']: mount for mount in container['Mounts']}
            for target, folder in expected[service].items():
                mount = mounts[target]
                # Docker Desktop reports native C:/ paths for these bind mounts.
                if mount['Type'] != 'bind' or Path(mount['Source']).resolve() != contained(self.root, self.root / folder):
                    raise ValueError('Runtime mount does not belong to this deployment')
            if service == 'alarm_rag':
                if mounts['/app/hf_cache']['RW']:
                    raise ValueError('Shared model cache must be read-only')
            elif any(container['HostConfig']['PortBindings'].values()):
                raise ValueError('Backend database ports must not be published')
            if service == 'qdrant':
                volume = mounts['/qdrant/storage']
                if (volume['Type'] != 'volume' or volume['Name'] != self.manifest['qdrant_volume']
                        or volume['Name'] != self.project + '_qdrant'):
                    raise ValueError('Qdrant must use this deployment\'s own named volume')
            result[service] = {'mounts': {k: v['Source'] for k, v in mounts.items()},
                               'networks': sorted(container['NetworkSettings']['Networks'])}
        return result

    def volume_archive(self, archive: Path, *, restore: bool = False):
        # Use the already installed application image; never mount another company's volume.
        self.validate_mounts()
        volume = self.manifest['qdrant_volume']
        code = """import pathlib,sys,tarfile,shutil
root=pathlib.Path('/runtime')
if sys.argv[1]=='backup':
 with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as tar:
  for path in root.iterdir(): tar.add(path,arcname=path.name)
else:
 with tarfile.open('/archive/qdrant.tar','r') as tar:
  members=tar.getmembers()
  for member in members:
   path=(root/member.name).resolve()
   if path==root or not path.is_relative_to(root) or not (member.isfile() or member.isdir()):
    raise ValueError('Unsafe archive member')
  for path in root.iterdir():
   if not path.resolve().is_relative_to(root) or path.is_symlink(): raise ValueError('Unsafe runtime path')
   if path.is_dir(): shutil.rmtree(path)
   else: path.unlink()
  tar.extractall(root,members=members,filter='data')
"""
        command = ['docker', 'run', '--rm', '--network', 'none', '--user', '0',
                   '--mount', f'type=volume,source={volume},target=/runtime' + ('' if restore else ',readonly')]
        if restore:
            command += ['--mount', f'type=bind,source={archive.parent},target=/archive,readonly']
        command += ['--entrypoint', 'python', self.manifest['image'], '-c', code, 'restore' if restore else 'backup']
        if restore:
            subprocess.run(command, check=True, capture_output=True)
        else:
            with archive.open('wb') as stream:
                subprocess.run(command, check=True, stdout=stream, stderr=subprocess.PIPE)

    def sql(self, query: str) -> str:
        return subprocess.check_output(['docker', 'exec', self.pg, 'psql', '-X', '-A', '-t',
                                        '-U', self.manifest['database_user'], '-d', self.manifest['database'],
                                        '-c', query], encoding='utf-8').strip()

    def database_state(self) -> dict:
        tables = self.sql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
        result = {}
        for table in tables:
            if not re.fullmatch(r'[a-z_][a-z0-9_]*', table):
                raise ValueError('Unexpected table name')
            rows = self.sql(f'SELECT row_to_json(t)::text FROM "{table}" t ORDER BY row_to_json(t)::text')
            result[table] = {'rows': int(self.sql(f'SELECT count(*) FROM "{table}"')),
                             'sha256': hashlib.sha256(rows.encode()).hexdigest()}
        return result

    def wait_ready(self, timeout: int = 180):
        deadline = time.monotonic() + timeout
        with httpx.Client(trust_env=False, timeout=3) as client:
            while time.monotonic() < deadline:
                try:
                    if client.get(self.base + '/health').status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(1)
        raise RuntimeError('Deployment did not become ready')

    def backup(self) -> Path:
        self.validate_mounts()
        destination = contained(self.root, self.root / 'backups' / ('company-' + uuid.uuid4().hex[:12]))
        destination.mkdir(parents=True)
        try:
            self.compose('stop', 'alarm_rag', 'qdrant')
            with (destination / 'postgres.dump').open('wb') as stream:
                subprocess.run(['docker', 'exec', self.pg, 'pg_dump', '-Fc', '--no-owner', '--no-privileges',
                                '-U', self.manifest['database_user'], '-d', self.manifest['database']],
                               stdout=stream, stderr=subprocess.PIPE, check=True)
            for name in RUNTIME:
                source = contained(self.root, self.root / name)
                hashes(source)  # Reject links before copytree follows them.
                shutil.copytree(source, destination / name)
            self.volume_archive(destination / 'qdrant.tar')
            manifest = {'schema_version': 1, 'project': self.project, 'database': self.manifest['database'],
                        'company_id': self.manifest['company_id'], 'deployment_directory': str(self.root),
                        'database_state': self.database_state(), 'files': hashes(destination)}
            (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        finally:
            self.compose('up', '-d', 'qdrant', 'alarm_rag')
            self.wait_ready()
        return destination

    def validate_backup(self, source: Path) -> dict:
        source = contained(self.root, source)
        manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
        if (manifest['schema_version'] != 1 or manifest['project'] != self.project
                or manifest['database'] != self.manifest['database']
                or manifest['company_id'] != self.manifest['company_id']
                or Path(manifest['deployment_directory']).resolve() != self.root):
            raise ValueError('Backup belongs to a different deployment')
        actual = hashes(source)
        actual.pop('manifest.json', None)
        if actual != manifest['files'] or not {'postgres.dump', 'qdrant.tar'} <= actual.keys():
            raise ValueError('Backup checksum mismatch')
        if any(not (source / name).is_dir() for name in RUNTIME):
            raise ValueError('Backup runtime directories are missing')
        return manifest

    def restore(self, source: Path) -> dict:
        source = contained(self.root, source)
        manifest = self.validate_backup(source)
        self.validate_mounts()
        quarantine = contained(self.root, self.root / 'backups' / ('before-restore-' + uuid.uuid4().hex[:12]))
        quarantine.mkdir()
        try:
            self.compose('stop', 'alarm_rag', 'qdrant')
            self.volume_archive(quarantine / 'qdrant.tar')
            with (quarantine / 'before-restore.dump').open('wb') as previous:
                subprocess.run(['docker', 'exec', self.pg, 'pg_dump', '-Fc', '--no-owner', '--no-privileges',
                                '-U', self.manifest['database_user'], '-d', self.manifest['database']],
                               stdout=previous, stderr=subprocess.PIPE, check=True)
            with (source / 'postgres.dump').open('rb') as stream:
                subprocess.run(['docker', 'exec', '-i', self.pg, 'pg_restore', '--clean', '--if-exists',
                                '--exit-on-error', '--no-owner', '--no-privileges', '--single-transaction',
                                '-U', self.manifest['database_user'], '-d', self.manifest['database']],
                               stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            for name in RUNTIME:
                current = contained(self.root, self.root / name)
                current.rename(contained(self.root, quarantine / name))
                shutil.copytree(source / name, current)
            self.volume_archive(source / 'qdrant.tar', restore=True)
            if self.database_state() != manifest['database_state']:
                raise RuntimeError('Restored database differs from backup')
            for name in RUNTIME:
                if hashes(self.root / name) != hashes(source / name):
                    raise RuntimeError('Restored runtime differs from backup')
        finally:
            self.compose('up', '-d', 'qdrant', 'alarm_rag')
            self.wait_ready()
        return {'database_matches': True, 'runtime_matches': True, 'quarantine': str(quarantine)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment', type=Path, required=True)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('backup')
    restore = commands.add_parser('restore')
    restore.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    deployment = Deployment(args.deployment)
    result = deployment.backup() if args.action == 'backup' else deployment.restore(args.backup)
    print(result)


if __name__ == '__main__':
    main()
