import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts import init_company_deployment as initializer
from scripts import company_service


@pytest.mark.parametrize('failure,expected', [
    ('info', 'Linux containers'), ('image', 'image missing'),
    ('config', 'Compose validation failed'), ('timeout', 'Docker unavailable'),
])
def test_prerequisite_failure_leaves_target_absent(tmp_path, monkeypatch, failure, expected):
    def command(args, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(args, 60, stderr='private-credential')
        if failure in args and failure != 'info':
            raise subprocess.CalledProcessError(1, args, stderr='private-credential')
        return SimpleNamespace(stdout=('windows' if failure == 'info' else 'linux') if 'info' in args else '')
    monkeypatch.setattr(initializer.subprocess, 'run', command)
    monkeypatch.setattr(initializer, 'check_host_port', lambda _: None)
    with pytest.raises(initializer.PreparationError, match=expected) as error:
        initializer.prepare_deployment(tmp_path / 'company', initializer.ROOT / 'templates/company.cnc-demo.json',
            project='test-setup', port=8191, cache=tmp_path, image='local:test', embedding='e', reranker='r')
    assert 'private-credential' not in str(error.value)
    assert not (tmp_path / 'company').exists()


def test_render_ignores_shell_and_dotenv_but_preserves_docker_connection(monkeypatch):
    monkeypatch.setenv('ALARM_RAG_BIND_ADDRESS', '0.0.0.0')
    monkeypatch.setenv('VECTOR_STORE', 'faiss')
    monkeypatch.setenv('COMPOSE_PROFILES', 'automation')
    monkeypatch.setenv('COMPOSE_ENV_FILES', 'other-company.env')
    monkeypatch.setenv('DOCKER_HOST', 'test-docker-endpoint')
    temporary = []
    def command(args, **kwargs):
        environment = kwargs['env']
        assert 'ALARM_RAG_BIND_ADDRESS' not in environment
        assert 'VECTOR_STORE' not in environment
        assert 'COMPOSE_PROFILES' not in environment
        assert 'COMPOSE_ENV_FILES' not in environment
        assert environment['DOCKER_HOST'] == 'test-docker-endpoint'
        assert environment['COMPOSE_PROJECT_NAME'] == 'test-company'
        env_file = Path(args[args.index('--env-file') + 1])
        assert env_file.read_bytes() == b''
        temporary.append(env_file)
        return SimpleNamespace(stdout='{"services":{}}')
    monkeypatch.setattr(initializer.subprocess, 'run', command)
    assert initializer.render_compose({'COMPOSE_PROJECT_NAME': 'test-company'}) == {'services': {}}
    assert not temporary[0].exists()


@pytest.mark.parametrize('action,command_tail', [
    ('start', ['up', '-d']), ('status', ['ps', '--all']),
    ('restart', ['restart']), ('stop', ['stop']),
])
def test_runtime_commands_use_company_env_instead_of_shell_secrets(tmp_path, monkeypatch, action, command_tail):
    (tmp_path / 'deployment.json').write_text(json.dumps({
        'directory': str(tmp_path), 'fresh_runtime': True, 'data_store': 'postgresql',
        'project': 'test-company', 'database': 'test_company', 'database_user': 'test_company', 'port': 8191}))
    (tmp_path / 'compose.company.json').write_text(json.dumps({'services': {'postgres': {
        'environment': {'POSTGRES_PASSWORD': '${POSTGRES_PASSWORD:?required}'}}}}))
    monkeypatch.setenv('POSTGRES_PASSWORD', 'wrong-company-password')
    monkeypatch.setenv('COMPOSE_PROJECT_NAME', 'other-company')
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        assert args[args.index('--project-name') + 1] == 'test-company'
        assert args[args.index('--env-file') + 1] == str(tmp_path / '.env')
        assert args[-len(command_tail):] == command_tail
        assert 'POSTGRES_PASSWORD' not in kwargs['env']
        assert 'COMPOSE_PROJECT_NAME' not in kwargs['env']
        return SimpleNamespace(stdout=b'')
    monkeypatch.setattr(initializer.subprocess, 'run', command)
    monkeypatch.setattr('sys.argv', ['company_service.py', '--deployment', str(tmp_path), action])
    assert company_service.main() == 0
    assert len(calls) == 1


def test_stop_failure_does_not_claim_shutdown_or_expose_compose_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['company_service.py', '--deployment', str(tmp_path), 'stop'])
    def fail(*args):
        raise subprocess.CalledProcessError(1, ['docker'], stderr=b'private-credential')
    monkeypatch.setattr(company_service, 'Deployment', lambda _: SimpleNamespace(compose=fail))
    with pytest.raises(SystemExit) as error:
        company_service.main()
    assert error.value.code == 1
    output = capsys.readouterr()
    assert 'shutdown is not confirmed' in output.err
    assert 'private-credential' not in output.err
    assert 'containers stopped' not in output.out


def test_modified_template_rejected_before_docker(tmp_path, monkeypatch):
    (tmp_path / 'template-manifest.json').write_text(json.dumps({
        'schema_version': 1, 'files': {'missing.py': 'not-present'}}))
    company_file = initializer.ROOT / 'templates/company.cnc-demo.json'
    monkeypatch.setattr(initializer, 'ROOT', tmp_path)
    monkeypatch.setattr(initializer.subprocess, 'run', lambda *a, **k: pytest.fail('Docker must not run'))
    with pytest.raises(initializer.PreparationError, match='Template files changed'):
        initializer.prepare_deployment(tmp_path / 'company', company_file,
            project='test-setup', port=8191, cache=tmp_path, image='local:test', embedding='e', reranker='r')
    assert not (tmp_path / 'company').exists()
