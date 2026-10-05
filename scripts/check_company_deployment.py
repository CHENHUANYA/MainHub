"""Read-only startup diagnostics for an initialized company deployment.

No login, account creation, document import or database cleanup is performed.
--probe-model sends one short inference request from the application container.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.company_runtime_backup import Deployment


# Print only explicit booleans. Neither environment variables nor model responses
# are returned to the host report; exceptions can contain private connection URLs.
MODEL_PROBE = r'''
import json, os, sys
import httpx
result = {'cache_present': False, 'ollama_reachable': False, 'model_installed': False}
try:
 from rag_engine import model_cache_status
 result['cache_present'] = model_cache_status()['ready'] is True
except Exception:
 pass
try:
 model = os.environ.get('OLLAMA_MODEL', 'gemma4:e2b')
 url = os.environ.get('OLLAMA_URL', 'http://host.docker.internal:11434').rstrip('/')
 with httpx.Client(trust_env=False, timeout=120) as client:
  tags = client.get(url + '/api/tags', timeout=5)
  tags.raise_for_status()
  names = {item['name'] for item in tags.json()['models']}
  result['ollama_reachable'] = True
  expected = model if ':' in model.rsplit('/', 1)[-1] else model + ':latest'
  result['model_installed'] = expected in names
  if sys.argv[1] == 'generate':
   result['model_answered'] = False
   if result['model_installed']:
    response = client.post(url + '/api/chat', json={
     'model': model, 'messages': [{'role': 'user', 'content': 'Reply with OK.'}],
     'stream': False, 'think': False, 'options': {'temperature': 0, 'num_predict': 32}})
    response.raise_for_status()
    payload = response.json()
    content = payload.get('message', {}).get('content')
    result['model_answered'] = (payload.get('done') is True and
     isinstance(content, str) and bool(content.strip()))
except Exception:
 pass
print('COMPANY_CHECK=' + json.dumps(result))
'''


def wait_ready(base: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    with httpx.Client(trust_env=False, timeout=3) as client:
        while True:
            try:
                response = client.get(base + '/ready')
                body = response.json()
                if (response.status_code == 200 and isinstance(body, dict)
                        and body.get('status') == 'ok'
                        and body.get('checks') == {'database': 'ok', 'vector_store': 'ok'}):
                    return True
            except (httpx.HTTPError, ValueError):
                pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(2, remaining))


def probe_models(project: str, generate: bool) -> dict:
    completed = subprocess.run(
        ['docker', 'exec', project + '-alarm_rag-1', 'python', '-c', MODEL_PROBE,
         'generate' if generate else 'tags'],
        check=True, capture_output=True, text=True, encoding='utf-8', timeout=160)
    line = next(line for line in reversed(completed.stdout.splitlines()) if line.startswith('COMPANY_CHECK='))
    result = json.loads(line.split('=', 1)[1])
    if not isinstance(result, dict):
        raise ValueError('Invalid model probe result')
    return result


def validate_endpoint(deployment: Deployment) -> None:
    result = subprocess.run(
        ['docker', 'inspect', '--format', '{{json .NetworkSettings.Ports}}',
         deployment.project + '-alarm_rag-1'],
        check=True, capture_output=True, text=True, timeout=30)
    bindings = json.loads(result.stdout).get('8000/tcp') or []
    if not any(b.get('HostPort') == str(deployment.manifest['port'])
               and b.get('HostIp') == '127.0.0.1' for b in bindings):
        raise ValueError('Application endpoint does not match deployment')


def check_deployment(directory: Path, *, timeout: float = 180, generate: bool = False) -> dict:
    checks = []

    def record(name: str, ok: bool, instruction: str) -> None:
        checks.append({'name': name, 'status': 'PASS' if ok else 'FAIL', 'next_step': '' if ok else instruction})

    try:
        deployment = Deployment(directory)
    except (OSError, ValueError, KeyError, TypeError):
        record('deployment', False, '確認 --deployment 指向初始化成功的公司目錄；不要重新初始化舊目錄。')
        return {'status': 'FAIL', 'checks': checks}
    try:
        deployment.validate_mounts()
        validate_endpoint(deployment)
        record('isolation', True, '')
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        record('isolation', False, '確認 Docker 已啟動，並依 SOP 第 4 步啟動此公司的三個服務；保留既有資料。')
        return {'status': 'FAIL', 'checks': checks}
    ready = wait_ready(deployment.base, timeout)
    record('database_and_vector_ready', ready, '服務尚未就緒；稍後重跑，持續失敗時保留報告交維護者處理。')
    if ready:
        try:
            model = probe_models(deployment.project, generate)
        except (OSError, subprocess.SubprocessError, ValueError, StopIteration):
            model = {}
        for name, instruction in (
            ('cache_present', '依 SOP 第 2 步準備兩個檢索模型，並核對初始化使用的快取目錄與模型名稱。'),
            ('ollama_reachable', '啟動主機 Ollama，依地端模型說明檢查容器至主機的連線。'),
            ('model_installed', '在主機執行 ollama pull gemma4:e2b，再重跑檢查。'),
            *([('model_answered', '確認主機 Ollama 能回答並有足夠記憶體，再重跑 --probe-model。')] if generate else []),
        ):
            record(name, model.get(name) is True, instruction)
    return {'status': 'PASS' if all(c['status'] == 'PASS' for c in checks) else 'FAIL',
            'checks': checks, 'generation_requested': generate,
            'scope': '啟動檢查；快取存在不代表模型成功載入，正式查詢與引用仍須完成 SOP 第 6、7 步。'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment', required=True, type=Path)
    parser.add_argument('--timeout', type=int, default=180, choices=range(1, 601), metavar='1..600')
    parser.add_argument('--probe-model', action='store_true')
    parser.add_argument('--report', type=Path, help='save a UTF-8 JSON report to a new file')
    args = parser.parse_args()
    if args.report and (args.report.exists() or not args.report.parent.is_dir()):
        parser.error('--report must be a new file in an existing directory')
    print('Checking deployment; startup and model inference may take several minutes.', file=sys.stderr, flush=True)
    result = check_deployment(args.deployment, timeout=args.timeout, generate=args.probe_model)
    if args.report:
        try:
            with args.report.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
        except OSError:
            parser.exit(1, 'Cannot save report; select a new writable report path.\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
