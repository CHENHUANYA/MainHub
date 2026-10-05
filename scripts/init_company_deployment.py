"""Create a fresh, isolated PostgreSQL deployment bundle. Never reuse old runtime data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.export_company_template import bundle_files
from services.company_config import CompanyConfig
from scripts.verify_template_bundle import verify
from scripts.company_compose import compose_environment


class PreparationError(ValueError):
    """A fixed, credential-free explanation suitable for the setup operator."""


def docker_command(args: list[str], *, stage: str, **kwargs):
    try:
        return subprocess.run(['docker', *args], capture_output=True, text=True,
                              encoding='utf-8', check=True, timeout=60, **kwargs)
    except (OSError, subprocess.SubprocessError):
        # Docker errors may contain resolved environment values. Show fixed guidance.
        raise PreparationError(stage) from None


def render_compose(values: dict[str, str]) -> dict:
    sources = [ROOT / 'docker-compose.yml', ROOT / 'docker-compose.postgresql.yml']
    environment = compose_environment('\n'.join(source.read_text(encoding='utf-8') for source in sources), values)
    # An explicit empty env file prevents Compose loading a developer's ROOT/.env.
    # Close it before Docker opens it on Windows; it contains no credentials.
    with tempfile.NamedTemporaryFile(prefix='mainthub-compose-', suffix='.env', delete=False) as stream:
        env_file = Path(stream.name)
    try:
        result = docker_command([
            'compose', '--env-file', str(env_file), '--project-directory', str(ROOT),
            '-f', str(sources[0]), '-f', str(sources[1]), 'config', '--format', 'json',
        ], env=environment, stage='Compose validation failed; check Docker Compose and re-extract the original package.')
        return json.loads(result.stdout)
    finally:
        env_file.unlink(missing_ok=True)


def check_host_port(port: int) -> None:
    """Catch non-Docker listeners too, without taking over their socket."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            raise PreparationError('Application port is occupied or reserved; select another port') from None


def prepare_deployment(output: Path, company_file: Path, *, project: str, port: int,
                       cache: Path, image: str, embedding: str, reranker: str) -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,40}", project):
        raise PreparationError("Project must contain 3-41 lowercase letters, digits or hyphens")
    if not 1024 <= port <= 65535:
        raise PreparationError("Port must be between 1024 and 65535")
    company = CompanyConfig.model_validate_json(company_file.read_text(encoding="utf-8"))
    output, cache = output.resolve(), cache.resolve()
    if not cache.is_dir():
        raise PreparationError("Model cache directory does not exist")
    if output.exists():
        raise PreparationError("Deployment directory already exists; select a new directory")
    if (ROOT / 'template-manifest.json').exists() and verify(ROOT)['status'] != 'PASS':
        raise PreparationError('Template files changed; re-extract the original package before initialization')
    check_host_port(port)
    # Check Docker project/port collisions before creating any files.
    containers = docker_command(['ps', '-a', '--filter', f'label=com.docker.compose.project={project}',
                                 '--format', '{{.ID}}'], stage='Docker unavailable; start Docker Desktop and retry.')
    if containers.stdout.strip():
        raise PreparationError("Compose project already has containers")
    published = docker_command(['ps', '--filter', f'publish={port}', '--format', '{{.ID}}'],
                               stage='Cannot check Docker ports; check Docker Desktop and retry.')
    if published.stdout.strip():
        raise PreparationError("Requested application port is already published")
    volumes = docker_command(['volume', 'ls', '--format', '{{.Name}}'],
                             stage='Cannot check Docker volumes; check Docker Desktop and retry.')
    if project + '_qdrant' in volumes.stdout.splitlines():
        raise PreparationError("Project Qdrant volume already exists; select a new project to avoid reusing old data")
    engine = docker_command(['info', '--format', '{{.OSType}}'],
                            stage='Docker unavailable; start Docker Desktop and retry.')
    if engine.stdout.strip() != 'linux':
        raise PreparationError('Docker must use Linux containers; switch Docker Desktop to Linux containers.')
    docker_command(['image', 'inspect', image, '--format', '{{.Id}}'],
                   stage='Application image missing; complete the SOP image build or correct --image.')
    sql_name = project.replace('-', '_')
    values = {
        'COMPOSE_PROJECT_NAME': project, 'DATA_STORE': 'postgresql', 'ALARM_RAG_ENV': 'production',
        'ALARM_RAG_PORT': str(port), 'ALARM_RAG_CORS_ORIGINS': f'http://127.0.0.1:{port},http://localhost:{port}',
        'ADMIN_INITIAL_PASSWORD': secrets.token_urlsafe(32), 'ALARM_RAG_INDEX_SIGNING_KEY': secrets.token_hex(32),
        'QDRANT_API_KEY': secrets.token_hex(32), 'POSTGRES_PASSWORD': secrets.token_urlsafe(32),
        'POSTGRES_DB': sql_name, 'POSTGRES_USER': sql_name,
        'SESSION_COOKIE_NAME': sql_name + '_session',
        'OLLAMA_URL': 'http://host.docker.internal:11434', 'OLLAMA_MODEL': 'gemma4:e2b',
        'RAG_EMBEDDING_MODEL': embedding, 'RAG_RERANKER_MODEL': reranker,
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'RAG_HF_LOCAL_ONLY': 'true',
    }
    config = render_compose(values)
    config['name'] = project
    config['services'].pop('n8n', None)
    app = config['services']['alarm_rag']
    app.pop('build', None)
    app['image'] = image
    app['volumes'] = [
        {'type': 'bind', 'source': str(output / name), 'target': '/app/' + name}
        for name in ('alarm_db', 'data', 'backups')
    ] + [{'type': 'bind', 'source': str(cache), 'target': '/app/hf_cache', 'read_only': True}]
    # Both backend services are private to this company's Compose network.
    for service in ('postgres', 'qdrant'):
        config['services'][service].pop('ports', None)
    config['services']['postgres']['volumes'] = [
        {'type': 'bind', 'source': str(output / 'postgres_data'), 'target': '/var/lib/postgresql/data'}]
    config['services']['postgres']['healthcheck']['test'] = [
        'CMD-SHELL', f'pg_isready -h 127.0.0.1 -U {sql_name} -d {sql_name}']
    # Qdrant requires a POSIX filesystem; Windows bind mounts corrupt mmap-backed payloads.
    config['services']['qdrant']['volumes'] = [
        {'type': 'volume', 'source': 'company_qdrant', 'target': '/qdrant/storage'}]
    config['volumes'] = {'company_qdrant': {'name': project + '_qdrant'}}
    # Persist placeholders, keeping credentials only in this deployment's .env.
    for service in config['services'].values():
        for key in list(service.get('environment', {})):
            secret_key = 'QDRANT_API_KEY' if key == 'QDRANT__SERVICE__API_KEY' else key
            if secret_key in {'ADMIN_INITIAL_PASSWORD', 'ALARM_RAG_INDEX_SIGNING_KEY', 'QDRANT_API_KEY', 'POSTGRES_PASSWORD'}:
                service['environment'][key] = '${' + secret_key + ':?Set deployment credential}'
    manifest = {'schema_version': 1, 'project': project, 'company_id': company.company.id,
                'port': port, 'database': sql_name, 'database_user': sql_name, 'data_store': 'postgresql',
                'directory': str(output), 'image': image, 'fresh_runtime': True,
                'qdrant_volume': project + '_qdrant',
                'shared_readonly_model_cache': str(cache)}
    # All external prerequisite checks finish before creating company files.
    output.mkdir(parents=True)
    for source in bundle_files():
        target = output / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    if (ROOT / 'template-manifest.json').is_file():
        shutil.copyfile(ROOT / 'template-manifest.json', output / 'template-manifest.json')
    for name in ('alarm_db', 'data', 'backups', 'qdrant_data', 'postgres_data'):
        (output / name).mkdir()
    (output / 'company.json').write_text(company.model_dump_json(indent=2), encoding='utf-8')
    (output / '.env').write_text(''.join(f'{k}={v}\n' for k, v in values.items()), encoding='utf-8')
    (output / 'compose.company.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    (output / 'deployment.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--company-config', type=Path, required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--hf-cache', type=Path, default=ROOT / 'hf_cache')
    parser.add_argument('--image', default='mainthub:local-acceptance')
    parser.add_argument('--embedding', default='intfloat/multilingual-e5-large')
    parser.add_argument('--reranker', default='BAAI/bge-reranker-v2-m3')
    args = parser.parse_args()
    try:
        result = prepare_deployment(args.output, args.company_config, project=args.project, port=args.port,
                                    cache=args.hf_cache, image=args.image, embedding=args.embedding, reranker=args.reranker)
    except PreparationError as exc:
        parser.exit(1, f'Deployment preparation failed: {exc}\n')
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Deployment preparation failed: {type(exc).__name__}. Check configuration and select a fresh directory.\n')
    print(f"Prepared {result['project']} at {result['directory']} (port {result['port']})")
    print(f'Start with: python scripts/company_service.py --deployment "{result["directory"]}" start')


if __name__ == '__main__':
    main()
