"""Run real browser role workflows against a fresh, explicitly marked demo deployment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import sys
import time

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def deployment_context(directory: Path) -> tuple[dict, dict, str]:
    directory = directory.resolve()
    deployment = json.loads((directory / 'deployment.json').read_text(encoding='utf-8'))
    company = json.loads((directory / 'company.json').read_text(encoding='utf-8'))
    if (Path(deployment['directory']).resolve() != directory or not deployment.get('fresh_runtime')
            or deployment['data_store'] != 'postgresql' or not company['company']['id'].startswith('demo-')):
        raise ValueError('This acceptance tool only mutates freshly prepared demo deployments')
    return deployment, company, f"http://127.0.0.1:{deployment['port']}"


def prepare_demo(directory: Path, pdf: Path) -> tuple[dict, dict, dict]:
    deployment, company, base = deployment_context(directory)
    credentials_file = directory / '.acceptance-credentials.json'
    if credentials_file.exists():
        credentials = json.loads(credentials_file.read_text(encoding='utf-8'))
    else:
        prefix = company['company']['id'].removeprefix('demo-')
        credentials = {role: {'username': 'admin01' if role == 'admin' else f'{prefix}_{role}',
                              'password': secrets.token_urlsafe(24)}
                       for role in ('admin', 'operator', 'maintenance', 'supervisor')}
        batch_credentials = directory / '.batch-acceptance/credentials.json'
        if batch_credentials.exists():
            credentials['admin']['password'] = json.loads(batch_credentials.read_text(encoding='utf-8'))['admin']
        credentials_file.write_text(json.dumps(credentials, indent=2), encoding='utf-8')
    with httpx.Client(base_url=base, trust_env=False, timeout=240) as client:
        admin = credentials['admin']
        login = client.post('/auth/login', json=admin)
        if login.status_code in (401, 403):
            initial = dotenv_values(directory / '.env')['ADMIN_INITIAL_PASSWORD']
            changed = client.post('/auth/initial-password', json={
                'username': 'admin01', 'current_password': initial, 'new_password': admin['password']})
            changed.raise_for_status()
            login = client.post('/auth/login', json=admin)
        login.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + login.json()['token']
        preview = client.post('/company-config/preview', json={'config': company}).json()
        applied = client.put('/company-config', json={'config': company, 'expected_revision': preview['expected_revision']}).json()
        if applied.get('status') != 'ok':
            raise ValueError('Company configuration could not be applied')
        users = {u['user_id'] for u in client.get('/users').json()['users']}
        for role, account in credentials.items():
            if role == 'admin' or account['username'] in users:
                continue
            created = client.post('/users', json={
                'user_id': account['username'], 'password': account['password'], 'role': role,
                'name': f'MOCK {role}', 'line_scope': [company['machines'][0]['line_id']],
            }).json()
            if created.get('status') != 'ok':
                raise ValueError(f'Could not create {role} demo account')
            initial_password = account['password']
            account['password'] = secrets.token_urlsafe(24)
            credentials_file.write_text(json.dumps(credentials, indent=2), encoding='utf-8')
            changed = client.post('/auth/initial-password', json={
                'username': account['username'], 'current_password': initial_password,
                'new_password': account['password']})
            changed.raise_for_status()
        collection = company['default_collection']
        ingest = client.post(f'/v1/{collection}/ingest', files={'file': (pdf.name, pdf.read_bytes(), 'application/pdf')})
        if ingest.status_code not in (200, 409) or ingest.json().get('status') not in ('ok', 'duplicate'):
            raise ValueError('Demo PDF import failed')
        client.post('/auth/logout')
    return deployment, company, credentials


def browser_workflow(directory: Path, pdf: Path, output: Path, *, knowledge_action: str = 'approve') -> dict:
    from playwright.sync_api import sync_playwright, expect
    from scripts.verify_local_rag import evaluate_evidence
    import hashlib

    deployment, company, credentials = prepare_demo(directory, pdf)
    base = f"http://127.0.0.1:{deployment['port']}"
    machine = company['machines'][0]
    report: dict = {'status': 'FAIL', 'project': deployment['project'], 'company': company['company']['id'],
                    'mode': 'Real headless Edge, cookie login, PostgreSQL, Qdrant and host Ollama; MOCK DATA',
                    'checks': [], 'browser_errors': []}
    output.mkdir(parents=True, exist_ok=False)
    def passed(label):
        report['checks'].append(label)
        print(f"PASS {deployment['project']}: {label}", flush=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='msedge', headless=True)
        contexts = []
        pages = {}
        try:
            def login(role):
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                contexts.append(context)
                page = context.new_page()
                page.set_default_timeout(20000)
                page.on('pageerror', lambda exc: report['browser_errors'].append(str(exc)))
                page.goto(base + '/login', wait_until='domcontentloaded')
                page.locator('#loginUsername').fill(credentials[role]['username'])
                page.locator('#loginPassword').fill(credentials[role]['password'])
                page.locator('#loginSubmit').click()
                page.wait_for_url(base + '/' + role)
                expect(page.locator('.auth-logout')).to_be_visible()
                pages[role] = page
                passed(f'{role} browser login')
                return page
            def shot(page, name):
                page.screenshot(path=str(output / (name + '.png')), full_page=True)
            def mutate(page, action, path, method='PATCH', timeout=30000):
                with page.expect_response(lambda r: r.url == base + path and r.request.method == method, timeout=timeout) as response:
                    action()
                payload = response.value.json()
                if payload.get('status') != 'ok':
                    raise AssertionError(f'{path}: {payload.get("message", payload)}')
                return payload

            operator = login('operator')
            expect(operator.locator('#issueManual')).to_have_value(machine['collection'])
            operator.locator('#issueMachine').select_option(machine['id'])
            question = f"In the source PDF {pdf.name}, what does the training observation say about the gauge reading and reporting to maintenance?"
            operator.locator('#issueDescription').fill(question)
            with operator.expect_response(lambda r: r.url.endswith('/chat/completions'), timeout=240000) as response:
                operator.get_by_role('button', name='查詢初步建議', exact=True).click()
            query = response.value.json()
            record = operator.request.get(base + '/rag/answers/' + query['id']).json()
            admin = login('admin')
            health = admin.request.get(base + '/health/details').json()
            checks = evaluate_evidence(query, record, health, collection=machine['collection'], model='gemma4:e2b',
                                       source=pdf.name, page=1, source_hash=hashlib.sha256(pdf.read_bytes()).hexdigest(),
                                       required_terms=[], require_first_citation=False)
            answer_text = record['answer']['answer'].casefold()
            checks['answer_contains_expected_actions'] = all(
                any(term in answer_text for term in alternatives)
                for alternatives in (('gauge', '儀表', '壓力表'), ('maintenance', '維修', '維護')))
            report['rag'] = {'checks': checks, 'query': query, 'answer_record': record,
                             'citation_policy': 'Expected PDF/page/hash must be cited; approved work orders may rank before it',
                             'retrieval_runtime': health['collections'][machine['collection']]['retrieval_runtime']}
            if not all(checks.values()):
                raise AssertionError(f'Real RAG check failed: {checks}')
            expect(operator.locator('#operatorSuggestionBox')).not_to_contain_text('查詢中...')
            shot(operator, '01-operator-query')
            passed('real Ollama answer and expected document/page/hash')
            # Each repeat is a distinct MOCK scenario; identical knowledge is intentionally rejected.
            report['mock_scenario'] = 'MOCK-FLOW-' + secrets.token_hex(4)
            operator.locator('#issueAlarmCode').fill(report['mock_scenario'])
            with operator.expect_response(lambda r: r.url == base + '/issues' and r.request.method == 'POST') as created:
                operator.get_by_role('button', name='送出並通知維修', exact=True).click()
            payload = created.value.json()
            if payload.get('status') != 'ok':
                raise AssertionError(payload)
            issue = payload['issue']
            # Escalation happens in a second request after issue creation.
            expect(operator.locator('#issueResult')).to_contain_text('已建立問題')
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                current = operator.request.get(base + '/issues/' + issue['issue_id']).json()['issue']
                if current.get('work_order_id'):
                    break
                time.sleep(.2)
            order_id = current.get('work_order_id')
            if not order_id:
                raise AssertionError('Issue did not create a linked work order')
            report.update(issue_id=issue['issue_id'], work_order_id=order_id)
            shot(operator, '02-operator-reported')
            passed('operator reports issue and creates linked work order')

            supervisor = login('supervisor')
            supervisor.locator('[data-supervisor-section-target="responsibility"]').click()
            supervisor.locator('[id="svAssignee_' + order_id + '"]').select_option(credentials['maintenance']['username'])
            result = mutate(supervisor, lambda: supervisor.locator(
                '[data-on-click="updateSupervisorOrder"][data-action-args*="' + order_id + '"]').click(), '/work-orders/' + order_id)
            if result['order']['assigned_to'] != credentials['maintenance']['username']:
                raise AssertionError('Assignee mismatch')
            shot(supervisor, '03-supervisor-assigned')
            passed('supervisor assigns maintenance account')

            maintenance = login('maintenance')
            result = mutate(maintenance, lambda: maintenance.locator(
                '[data-on-click="startWorkOrder"][data-action-args*="' + order_id + '"]').click(), '/work-orders/' + order_id)
            assert result['order']['status'] == 'in_progress'
            maintenance.locator('[data-on-click="completeWorkOrder"][data-action-args*="' + order_id + '"]').click()
            expect(maintenance.locator('#maintenanceModal')).to_have_class('wo-modal show')
            maintenance.locator('#mtEditRootCause').fill('MOCK training observation; no real equipment fault')
            maintenance.locator('#mtEditRepairAction').fill('MOCK recorded gauge reading and notified maintenance')
            maintenance.locator('#mtEditResolution').fill('MOCK training verification completed')
            result = mutate(maintenance, lambda: maintenance.locator('[data-on-click="saveMaintenanceWorkOrder"]').click(), '/work-orders/' + order_id)
            assert result['order']['status'] == 'completed'
            shot(maintenance, '04-maintenance-completed')
            passed('maintenance starts and completes repair with required fields')

            operator.reload(wait_until='domcontentloaded')
            operator.locator('[data-issue-id="' + issue['issue_id'] + '"]').click()
            expect(operator.locator('#operatorIssueModal')).to_have_class('wo-modal show')
            # Operator verification routes through the linked issue workflow.
            with operator.expect_response(lambda r: r.request.method == 'PATCH' and '/issues/' in r.url) as verified:
                operator.locator('[data-on-click="verifyOperatorIssue"]').click()
            if verified.value.json().get('status') != 'ok':
                raise AssertionError('Operator verification failed')
            final_order = admin.request.get(base + '/work-orders/' + order_id).json()['order']
            assert final_order['status'] == 'verified' and final_order['kb_review_status'] == 'pending_review'
            shot(operator, '05-operator-verified')
            passed('operator verifies; knowledge remains pending review')

            admin.reload(wait_until='domcontentloaded')
            # Console data renders after async company configuration and navigation bindings.
            expect(admin.locator('#adminQualityList')).to_contain_text(order_id)
            admin.locator('[data-admin-section-target="quality"]').click()
            def review(label, note=''):
                admin.locator('[data-on-click="reviewAdminKnowledge"][data-action-args*="' + order_id + '"]').filter(
                    has_text=label).click()
                expect(admin.locator('#adminKnowledgeReviewForm')).to_be_visible()
                if note:
                    admin.locator('#adminKnowledgeReviewNote').fill(note)
                return mutate(admin, lambda: admin.locator('#adminKnowledgeReviewSubmit').click(),
                              '/work-orders/' + order_id + '/knowledge-review', method='POST', timeout=240000)

            if knowledge_action == 'approve':
                note = 'MOCK acceptance: supplement the training observation and record the outcome.'
                revised = review('退回補充', note)
                assert revised['order']['kb_review_status'] == 'needs_revision'
                assert revised['order']['status'] == 'verified'
                shot(admin, '06-admin-returned')
                passed('administrator returns verified knowledge for supplementation')
                maintenance.reload(wait_until='domcontentloaded')
                card = maintenance.locator('.wo-card[data-on-click="openMaintenanceModal"][data-action-args*="' + order_id + '"]')
                expect(card).to_be_visible()
                card.click()
                expect(maintenance.locator('#mtKnowledgeReview')).to_contain_text(note)
                expect(maintenance.locator('#mtEditStatus')).to_be_disabled()
                expect(maintenance.locator('#mtSaveOrder')).to_have_text('補充並重新送審')
                supplement = 'MOCK supplemental observation: gauge reading recorded; maintenance notified.'
                maintenance.locator('#mtEditNotes').fill(supplement)
                resubmitted = mutate(maintenance, lambda: maintenance.locator('#mtSaveOrder').click(), '/work-orders/' + order_id)
                assert resubmitted['order']['kb_review_status'] == 'pending_review'
                assert resubmitted['order']['status'] == 'verified'
                assert resubmitted['order']['verified_by'] == final_order['verified_by']
                expect(card).to_have_count(0)
                shot(maintenance, '07-maintenance-resubmitted')
                passed('assigned maintenance supplements and resubmits without changing verification')
                admin.reload(wait_until='domcontentloaded')
                expect(admin.locator('#adminQualityList')).to_contain_text(order_id)
                admin.locator('[data-admin-section-target="quality"]').click()
                row = admin.locator('#adminQualityList .quality-row').filter(has_text=order_id)
                row.locator('summary').click()
                for field in ('root_cause', 'repair_action', 'resolution', 'notes'):
                    expect(row).to_contain_text(resubmitted['order'][field])
                passed('administrator sees all four maintenance fields before approval')
                result = review('核准加入知識庫')
                assert result['order']['kb_review_status'] == 'ingested'
                assert result['ingest']['validation']['retrieval_hit']
                report['knowledge_doc_id'] = result['ingest']['doc_id']
                passed('admin approves knowledge and real retrieval validation passes')
            else:
                result = review('不採用', 'MOCK acceptance: training record excluded from knowledge.')
                assert result['order']['kb_review_status'] == 'rejected'
                assert result['order']['status'] == 'verified'
                assert not result['order'].get('kb_ingested_at')
                passed('administrator rejects knowledge while preserving verified work order')
            report['knowledge_action'] = knowledge_action
            report['final_order'] = result['order']
            expect(admin.locator('[data-on-click="reviewAdminKnowledge"][data-action-args*="' + order_id + '"]')).to_have_count(0)
            shot(admin, '08-admin-' + knowledge_action)
            if report['browser_errors']:
                raise AssertionError('Browser raised JavaScript errors')
            report['status'] = 'PASS'
        except Exception as exc:
            report['error'] = f'{type(exc).__name__}: {exc}'
            for role, page in pages.items():
                shot(page, 'failure-' + role)
        finally:
            for context in contexts:
                context.close()
            browser.close()
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment', type=Path, required=True)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--knowledge-action', choices=('approve', 'reject'), default='approve')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a fresh report directory')
    report = browser_workflow(args.deployment.resolve(), args.pdf.resolve(), args.output.resolve(),
                              knowledge_action=args.knowledge_action)
    print(f"{report['status']}: {args.output / 'report.json'}")
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
