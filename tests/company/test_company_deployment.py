import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import init_company_deployment as initializer
from scripts.company_runtime_backup import Deployment, contained, hashes
from services.auth_sessions import session_cookie_name


@pytest.mark.parametrize('value', ['bad;cookie', '../name', 'a b', 'x' * 65, 'name=value'])
def test_invalid_cookie_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        session_cookie_name(value)


def test_cookie_names_support_independent_companies_and_default():
    assert session_cookie_name('') == 'alarm_rag_session'
    assert session_cookie_name(' cnc_session ') == 'cnc_session'
    assert session_cookie_name('air_session') != session_cookie_name('cnc_session')


def test_prepared_companies_share_only_readonly_models(tmp_path, monkeypatch):
    cache = tmp_path / 'models'
    cache.mkdir()
    monkeypatch.setattr(initializer, 'bundle_files', lambda: [])
    def command(args, **kwargs):
        if 'info' in args:
            return SimpleNamespace(stdout='linux')
        if 'config' not in args:
            return SimpleNamespace(stdout='')
        env = kwargs['env']
        return SimpleNamespace(stdout=json.dumps({'services': {
            'alarm_rag': {'build': '.', 'environment': dict(env)},
            'postgres': {'ports': ['5432'], 'healthcheck': {}},
            'qdrant': {'ports': ['6333']}, 'n8n': {},
        }}))
    monkeypatch.setattr(initializer.subprocess, 'run', command)
    for name, port in (('cnc', 8131), ('air', 8132)):
        directory = tmp_path / name
        result = initializer.prepare_deployment(directory, initializer.ROOT / 'templates/company.cnc-demo.json',
            project='test-' + name, port=port, cache=cache, image='test:image', embedding='cached', reranker='cached')
        config = json.loads((directory / 'compose.company.json').read_text())
        assert result['qdrant_volume'] == 'test-' + name + '_qdrant'
        app = config['services']['alarm_rag']
        assert app['environment']['SESSION_COOKIE_NAME'] == 'test_' + name + '_session'
        assert app['environment']['POSTGRES_PASSWORD'].startswith('${')
        assert app['volumes'][-1]['read_only'] is True
        assert all(Path(v['source']).is_relative_to(directory) for v in app['volumes'][:-1])
        assert config['services']['qdrant']['volumes'][0]['type'] == 'volume'
        assert 'ports' not in config['services']['postgres']
        assert 'ports' not in config['services']['qdrant']
        assert not list((directory / 'alarm_db').iterdir())
    with pytest.raises(ValueError, match='already exists'):
        initializer.prepare_deployment(tmp_path / 'cnc', initializer.ROOT / 'templates/company.cnc-demo.json',
            project='test-cnc', port=8131, cache=cache, image='test', embedding='e', reranker='r')
    monkeypatch.setattr(initializer.subprocess, 'run', lambda args, **kwargs:
                        SimpleNamespace(stdout='test-old_qdrant\n' if 'volume' in args else ''))
    with pytest.raises(ValueError, match='volume already exists'):
        initializer.prepare_deployment(tmp_path / 'old', initializer.ROOT / 'templates/company.cnc-demo.json',
            project='test-old', port=8133, cache=cache, image='test', embedding='e', reranker='r')
    assert not (tmp_path / 'old').exists()


def test_restore_rejects_cross_company_paths_and_modified_backup_before_docker(tmp_path):
    root = tmp_path / 'company-a'
    root.mkdir()
    manifest = {'directory': str(root), 'fresh_runtime': True, 'data_store': 'postgresql',
                'project': 'test-cnc', 'database': 'test_cnc', 'database_user': 'test_cnc',
                'company_id': 'demo-cnc', 'port': 8131}
    (root / 'deployment.json').write_text(json.dumps(manifest))
    deployment = Deployment(root)
    with pytest.raises(ValueError, match='inside'):
        deployment.restore(tmp_path / 'company-b' / 'backups')
    with pytest.raises(ValueError, match='inside'):
        contained(root, root)
    backup = root / 'backups' / 'one'
    backup.mkdir(parents=True)
    for directory in ('alarm_db', 'data'):
        (backup / directory).mkdir()
    for name in ('postgres.dump', 'qdrant.tar'):
        (backup / name).write_bytes(b'snapshot')
    backup_manifest = {'schema_version': 1, 'project': 'test-cnc', 'database': 'test_cnc',
                       'company_id': 'demo-cnc', 'deployment_directory': str(root), 'files': hashes(backup)}
    (backup / 'manifest.json').write_text(json.dumps(backup_manifest))
    assert deployment.validate_backup(backup) == backup_manifest
    (backup / 'postgres.dump').write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='checksum'):
        deployment.restore(backup)
    backup_manifest['project'] = 'test-air'
    (backup / 'manifest.json').write_text(json.dumps(backup_manifest))
    with pytest.raises(ValueError, match='different deployment'):
        deployment.restore(backup)
