import json
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import check_company_deployment as checker
from scripts import init_company_deployment as initializer


def test_non_docker_listener_blocks_initialization_before_any_write(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(ValueError, match='occupied or reserved'):
            initializer.prepare_deployment(
                tmp_path / 'new', initializer.ROOT / 'templates/company.cnc-demo.json',
                project='test-new', port=port, cache=tmp_path, image='test', embedding='e', reranker='r')
        assert not (tmp_path / 'new').exists()


@pytest.mark.parametrize('status,body,expected', [
    (200, {'status': 'ok', 'checks': {'database': 'ok', 'vector_store': 'ok'}}, True),
    (200, {'status': 'ok'}, False),
    (200, {'status': 'ok', 'checks': {'database': 'not-required', 'vector_store': 'ok'}}, False),
    (503, {'status': 'unavailable', 'checks': {'database': 'unavailable', 'vector_store': 'ok'}}, False),
    (200, [], False),
])
def test_readiness_requires_both_dependencies(monkeypatch, status, body, expected):
    client_class = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    monkeypatch.setattr(checker.httpx, 'Client', lambda **kwargs: client_class(transport=transport, **kwargs))
    assert checker.wait_ready('http://127.0.0.1:8000', 0) is expected


@pytest.fixture
def running_deployment(monkeypatch):
    deployment = SimpleNamespace(project='test-company', base='http://127.0.0.1:8131',
                                 manifest={'port': 8131}, validate_mounts=lambda: {})
    monkeypatch.setattr(checker, 'Deployment', lambda _: deployment)
    monkeypatch.setattr(checker, 'validate_endpoint', lambda _: None)
    monkeypatch.setattr(checker, 'wait_ready', lambda *args: True)
    return deployment


def test_failed_model_probe_is_redacted(monkeypatch, running_deployment):
    def fail(*args):
        raise subprocess.CalledProcessError(1, ['private-password'], stderr='private-password')
    monkeypatch.setattr(checker, 'probe_models', fail)
    result = checker.check_deployment(Path('.'), generate=True)
    assert result['status'] == 'FAIL'
    assert 'private-password' not in json.dumps(result)
    assert len([c for c in result['checks'] if c['status'] == 'FAIL']) == 4


def test_installed_model_without_answer_is_not_generation_success(monkeypatch, running_deployment):
    monkeypatch.setattr(checker, 'probe_models', lambda *args: {
        'cache_present': True, 'ollama_reachable': True, 'model_installed': True, 'model_answered': False})
    assert checker.check_deployment(Path('.'), generate=True)['status'] == 'FAIL'
    result = checker.check_deployment(Path('.'))
    assert result['status'] == 'PASS'
    assert result['generation_requested'] is False
    assert 'model_answered' not in {c['name'] for c in result['checks']}


def test_failed_isolation_stops_before_network_or_inference(monkeypatch, running_deployment):
    def fail():
        raise ValueError('private-key')
    running_deployment.validate_mounts = fail
    monkeypatch.setattr(checker, 'wait_ready', lambda *args: pytest.fail('must not probe unverified deployment'))
    result = checker.check_deployment(Path('.'))
    assert result['status'] == 'FAIL'
    assert len(result['checks']) == 1
    assert 'private-key' not in json.dumps(result)


def test_wrong_port_cannot_pass_using_another_company(monkeypatch):
    monkeypatch.setattr(checker.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=json.dumps({
        '8000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8132'}]})))
    with pytest.raises(ValueError, match='endpoint'):
        checker.validate_endpoint(SimpleNamespace(project='test-company', manifest={'port': 8131}))


@pytest.mark.parametrize('content,done,expected', [('OK', True, True), (None, True, False),
                                                ('  ', True, False), ('OK', False, False)])
def test_container_probe_requires_completed_text(monkeypatch, capsys, content, done, expected):
    def handler(request):
        return httpx.Response(200, json=(
            {'models': [{'name': 'gemma4:e2b'}]} if request.url.path == '/api/tags'
            else {'done': done, 'message': {'content': content}}))
    client_class = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: client_class(transport=transport, **kwargs))
    monkeypatch.setitem(sys.modules, 'rag_engine', SimpleNamespace(model_cache_status=lambda: {'ready': True}))
    monkeypatch.setattr(sys, 'argv', ['probe', 'generate'])
    monkeypatch.setenv('OLLAMA_MODEL', 'gemma4:e2b')
    monkeypatch.setenv('OLLAMA_URL', 'http://ollama.test')
    exec(compile(checker.MODEL_PROBE, '<container probe>', 'exec'), {})
    result = json.loads(capsys.readouterr().out.split('COMPANY_CHECK=')[1])
    assert result['model_answered'] is expected
