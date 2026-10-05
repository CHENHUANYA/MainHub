"""Exercise restart and full restore in BOTH directions, on marked demo deployments only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

import httpx
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.company_runtime_backup import Deployment, hashes
from scripts.verify_company_deployment import deployment_context


def vector_state(deployment):
    code = '''import os,json,hashlib,urllib.request
base='http://qdrant:6333'
def request(path, payload=None):
 req=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload else None,
   headers={'api-key':os.environ['QDRANT_API_KEY'],'Content-Type':'application/json'})
 return json.load(urllib.request.urlopen(req))['result']
result={}
for collection in request('/collections')['collections']:
 name=collection['name']; points=[]; offset=None
 while True:
  payload={'limit':100,'with_payload':True,'with_vector':True}
  if offset is not None: payload['offset']=offset
  page=request('/collections/'+name+'/points/scroll',payload); points+=page['points']
  offset=page.get('next_page_offset')
  if offset is None: break
 encoded=json.dumps(sorted(points,key=lambda p:str(p['id'])),sort_keys=True).encode()
 result[name]={'points':len(points),'sha256':hashlib.sha256(encoded).hexdigest()}
print(json.dumps(result))'''
    return json.loads(subprocess.check_output(['docker', 'exec', deployment.project + '-alarm_rag-1', 'python', '-c', code]))


def snapshot(deployment):
    return {'database': deployment.database_state(), 'vectors': vector_state(deployment),
            'files': {name: hashes(deployment.root / name) for name in ('alarm_db', 'data')}}


def browser_sessions(deployments, output):
    from playwright.sync_api import sync_playwright, expect
    accounts = [json.loads((d.root / '.acceptance-credentials.json').read_text()) for d in deployments]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        try:
            pages = []
            for d, account in zip(deployments, accounts):
                page = context.new_page()
                page.goto(d.base + '/login')
                page.locator('#loginUsername').fill(account['admin']['username'])
                page.locator('#loginPassword').fill(account['admin']['password'])
                page.locator('#loginSubmit').click()
                page.wait_for_url(d.base + '/admin')
                expect(page.locator('.auth-logout')).to_be_visible()
                pages.append(page)
            for d, page in zip(deployments, pages):
                page.reload()
                expect(page.locator('.auth-logout')).to_be_visible()
                assert page.url == d.base + '/admin'
                page.screenshot(path=str(output / (d.project + '-simultaneous-login.png')), full_page=True)
            assert context.request.post(deployments[0].base + '/auth/logout').status == 200
            assert context.request.get(deployments[0].base + '/auth/me').status == 401
            assert context.request.get(deployments[1].base + '/auth/me').status == 200
            context.request.post(deployments[1].base + '/auth/logout')
        finally:
            browser.close()
    with httpx.Client(trust_env=False, timeout=20) as client:
        for index, d in enumerate(deployments):
            other = deployments[1-index]
            response = client.post(d.base + '/auth/login', json=accounts[index]['operator'])
            response.raise_for_status()
            token = response.json()['token']
            client.cookies.clear()
            assert client.get(other.base + '/auth/me', headers={'Authorization': 'Bearer ' + token}).status_code == 401
            assert client.post(other.base + '/auth/login', json=accounts[index]['operator']).status_code == 401
            client.post(d.base + '/auth/logout', headers={'Authorization': 'Bearer ' + token})


def verify_after_restore(deployment):
    account = json.loads((deployment.root / '.acceptance-credentials.json').read_text())['admin']
    company = json.loads((deployment.root / 'company.json').read_text(encoding='utf-8'))
    with httpx.Client(base_url=deployment.base, trust_env=False, timeout=240) as client:
        client.post('/auth/login', json=account).raise_for_status()
        response = client.post('/v1/' + company['default_collection'] + '/chat/completions', json={
            'model': 'gemma4:e2b', 'messages': [{'role': 'user', 'content':
                'According to the MOCK training document, what should be recorded and who should be notified?'}],
            'stream': False})
        response.raise_for_status()
        answer = response.json()
        assert answer['choices'][0]['message']['content'].strip()
        record = client.get('/rag/answers/' + answer['id']).json()
        stored = record['answer']
        assert stored['provider'] == 'ollama' and stored['model'] == 'gemma4:e2b'
        assert stored['answer_state'] == 'complete'
        assert stored['answer'] == answer['choices'][0]['message']['content']
        assert answer['rag']['collection'] == company['default_collection']
        assert any(c.get('source_hash') and c.get('page') == 1 for c in answer['rag']['citations'])
        client.post('/auth/logout')
        return {'answer': answer, 'record': record}


def run(deployments, output):
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'FAIL', 'checks': [], 'drills': []}
    def passed(label):
        report['checks'].append(label)
        print('PASS ' + label, flush=True)
    try:
        for d in deployments:
            deployment_context(d.root)
        for key in ('project', 'directory', 'port', 'database', 'database_user'):
            assert deployments[0].manifest[key] != deployments[1].manifest[key]
        envs = [dotenv_values(d.root / '.env') for d in deployments]
        for key in ('SESSION_COOKIE_NAME', 'ADMIN_INITIAL_PASSWORD', 'POSTGRES_PASSWORD', 'QDRANT_API_KEY', 'ALARM_RAG_INDEX_SIGNING_KEY'):
            assert envs[0][key] and envs[0][key] != envs[1][key]
        report['mounts'] = {d.project: d.validate_mounts() for d in deployments}
        passed('separate database identities, credentials, cookies, mounts and private service ports')
        browser_sessions(deployments, output)
        passed('same-browser simultaneous login and independent logout; cross-company account/token rejected')
        for index, target in enumerate(deployments):
            peer = deployments[1-index]
            before = snapshot(peer)
            stop = threading.Event()
            samples = []
            def monitor():
                with httpx.Client(trust_env=False, timeout=3) as client:
                    while not stop.is_set():
                        try:
                            samples.append(client.get(peer.base + '/health').status_code)
                        except httpx.HTTPError:
                            samples.append(0)
                        stop.wait(1)
            thread = threading.Thread(target=monitor, daemon=True)
            thread.start()
            drill = {'target': target.project, 'peer': peer.project}
            report['drills'].append(drill)
            try:
                initial = snapshot(target)
                target.compose('restart')
                target.wait_ready()
                assert snapshot(target) == initial
                passed(target.project + ' restart preserves database, documents and vectors')
                backup = target.backup()
                drill['backup'] = str(backup)
                marker = 'MOCK-RESTORE-' + uuid.uuid4().hex
                # Controlled fault after backup: one application setting and one document-side file.
                target.sql("INSERT INTO system_settings (key,value) VALUES ('" + marker + "','\"MOCK\"'::jsonb)")
                marker_path = target.root / 'data' / (marker + '.txt')
                marker_path.write_text('MOCK post-backup mutation', encoding='utf-8')
                assert target.sql("SELECT count(*) FROM system_settings WHERE key='" + marker + "'") == '1'
                drill['restore'] = target.restore(backup)
                assert not marker_path.exists()
                assert target.sql("SELECT count(*) FROM system_settings WHERE key='" + marker + "'") == '0'
                assert snapshot(target)['vectors'] == initial['vectors']
                passed(target.project + ' full restore removes later mutations and recovers identical database/files/vectors')
                drill['post_restore_query'] = verify_after_restore(target)
                passed(target.project + ' real model query succeeds after restore')
                assert snapshot(peer) == before
                passed(peer.project + ' database, document files and vector content unchanged')
            finally:
                stop.set()
                thread.join(5)
                drill['peer_health_probes'] = {'total': len(samples), 'failed': sum(s != 200 for s in samples)}
            assert samples and all(s == 200 for s in samples)
            passed(peer.project + ' remains available throughout peer restart/backup/restore')
        report['status'] = 'PASS'
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first', type=Path, required=True)
    parser.add_argument('--second', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run([Deployment(args.first), Deployment(args.second)], args.output)
    print(report['status'] + ': ' + str(args.output / 'report.json'))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
