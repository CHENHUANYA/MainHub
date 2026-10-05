"""Exercise batch import and first-password UI on a prepared MOCK company deployment.

Creates demo accounts/orders. Credentials and input workbooks stay in the deployment;
the separate evidence report contains no passwords. Never use on a real company.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import sys

from dotenv import dotenv_values
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify(directory: Path, output: Path) -> dict:
    from playwright.sync_api import sync_playwright, expect
    from scripts.verify_company_deployment import deployment_context

    deployment, company, base = deployment_context(directory)
    output.mkdir(parents=True, exist_ok=False)
    private = directory / '.batch-acceptance'
    private.mkdir(exist_ok=True)
    credentials_file = private / 'credentials.json'
    credentials = json.loads(credentials_file.read_text(encoding='utf-8')) if credentials_file.exists() else {
        'admin': secrets.token_urlsafe(24),
    }
    credentials_file.write_text(json.dumps(credentials), encoding='utf-8')
    initial = dotenv_values(directory / '.env')['ADMIN_INITIAL_PASSWORD']
    run = secrets.token_hex(4)
    user = 'batch_tech_' + run
    initial_user, personal_user = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    machine = company['machines'][0]
    report = {'status': 'FAIL', 'project': deployment['project'], 'checks': [], 'browser_errors': [],
              'mode': 'MOCK DATA; real Edge, cookie login and PostgreSQL'}

    def passed(label):
        report['checks'].append(label)
        print('PASS: ' + label, flush=True)

    def workbook(name, rows):
        book = Workbook()
        for row in rows:
            book.active.append(row)
        path = private / name
        book.save(path)
        book.close()
        return path

    def assert_redacted(value):
        text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        assert all(secret not in text for secret in (initial, credentials['admin'], initial_user, personal_user))
        assert 'password_hash' not in text

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on('pageerror', lambda error: report['browser_errors'].append(str(error)))
        try:
            def sign_in(target, username, password):
                target.goto(base + '/login')
                target.locator('#loginUsername').fill(username)
                target.locator('#loginPassword').fill(password)
                with target.expect_response(lambda r: r.url == base + '/auth/login') as response:
                    target.locator('#loginSubmit').click()
                # Navigation can discard Chromium's response body after a
                # successful login; only errors need their structured payload.
                if response.value.ok:
                    return {'status': 'ok'}
                return response.value.json()

            def change_password(target, password):
                expect(target.locator('#initialPasswordForm')).to_be_visible()
                target.locator('#initialNewPassword').fill(password)
                target.locator('#initialConfirmPassword').fill(password + 'mismatch')
                target.locator('#initialPasswordSubmit').click()
                expect(target.locator('#initialPasswordResult')).to_contain_text('不一致')
                target.locator('#initialConfirmPassword').fill(password)
                with target.expect_response(lambda r: r.url == base + '/auth/initial-password') as response:
                    target.locator('#initialPasswordSubmit').click()
                assert response.value.json()['status'] == 'ok'
                expect(target.locator('#loginForm')).to_be_visible()
                expect(target.locator('#loginPassword')).to_have_value('')
                expect(target.locator('#initialNewPassword')).to_have_value('')

            login = sign_in(page, 'admin01', credentials['admin'])
            if login.get('status') != 'ok':
                login = sign_in(page, 'admin01', initial)
            if login.get('error_code') == 'PASSWORD_CHANGE_REQUIRED':
                page.screenshot(path=str(output / '01-initial-password.png'))
                change_password(page, credentials['admin'])
                passed('administrator changes initial password entirely in browser')
            assert sign_in(page, 'admin01', credentials['admin'])['status'] == 'ok'
            page.wait_for_url(base + '/admin')
            expect(page.locator('#adminUserLabel')).to_contain_text('admin01')
            page.locator('[data-admin-section-target="settings"]').click()
            page.locator('#companyConfigFile').set_input_files(str(directory / 'company.json'))
            page.locator('#previewCompanyConfig').click()
            expect(page.locator('#applyCompanyConfig')).to_be_enabled()
            with page.expect_navigation(wait_until='domcontentloaded'):
                with page.expect_response(lambda r: r.url == base + '/company-config' and r.request.method == 'PUT') as applied:
                    page.locator('#applyCompanyConfig').click()
            assert applied.value.ok
            assert page.request.get(base + '/company-config').json()['company']['id'] == company['company']['id']
            expect(page.locator('#adminUserLabel')).to_contain_text('admin01')
            passed('company configuration applied through browser')
            page.locator('[data-admin-section-target="users"]').click()
            page.locator('#adminImportUsersPanel > summary').click()
            with page.expect_download() as download:
                page.locator('#adminImportUsersPanel').get_by_role('link', name='下載 Excel 範本').click()
            download.value.save_as(str(output / 'users-template.xlsx'))
            passed('administrator downloads blank personnel template')

            users = workbook('MOCK-users-' + run + '.xlsx', [
                ['user_id', 'name', 'role', 'team', 'line_scope', 'password'],
                [user, 'MOCK Technician', 'maintenance', 'MOCK', machine['line_id'], initial_user],
                [user, 'MOCK duplicate', 'maintenance', '', machine['line_id'], initial_user],
                ['invalid_' + run, 'MOCK invalid', 'unknown', '', machine['line_id'], initial_user],
                ['outside_' + run, 'MOCK outside', 'operator', '', 'unknown_line', initial_user],
            ])
            before_users = page.request.get(base + '/users').json()
            before_total = page.request.get(base + '/imports/batches').json()['total']

            def preview(path, kind):
                people = kind == 'users'
                selector = '#adminUserExcelFile' if people else '#adminExcelFile'
                endpoint = '/users/import-excel' if people else '/work-orders/import-excel'
                with page.expect_response(lambda r: r.url == base + endpoint + '/preview') as response:
                    page.locator(selector).set_input_files(str(path))
                data = response.value.json()
                assert data['status'] == 'ok', data
                assert_redacted(data)
                return data

            previewed = preview(users, 'users')
            assert (previewed['valid'], previewed['skipped']) == (1, 3)
            result = page.locator('#adminUserExcelResult')
            assert_redacted(result.inner_text())
            expect(result).to_contain_text('尚未寫入')
            page.screenshot(path=str(output / '02-user-preview.png'), full_page=True)
            result.get_by_role('button', name='取消', exact=True).click()
            assert page.request.get(base + '/users').json() == before_users
            assert page.request.get(base + '/imports/batches').json()['total'] == before_total
            passed('preview errors and cancellation leave accounts and history unchanged')
            preview(users, 'users')
            with page.expect_response(lambda r: r.url == base + '/users/import-excel') as response:
                result.get_by_role('button', name='確認匯入 1 筆有效帳號').click()
            created = response.value.json()
            assert created['status'] == 'ok' and created['imported'] == 1 and created['skipped'] == 3
            expect(result).to_contain_text('匯入完成')
            user_batch = created['batch_id']
            passed('confirmation creates only valid account and persistent batch history')
            assert preview(users, 'users')['valid'] == 0
            expect(result.get_by_role('button', name='確認匯入 0 筆有效帳號')).to_be_disabled()
            passed('repeat upload cannot overwrite an account')

            tech_context = browser.new_context()
            tech = tech_context.new_page()
            assert sign_in(tech, user, initial_user)['error_code'] == 'PASSWORD_CHANGE_REQUIRED'
            change_password(tech, personal_user)
            assert sign_in(tech, user, personal_user)['status'] == 'ok'
            tech.wait_for_url(base + '/maintenance')
            assert tech.request.get(base + '/imports/batches').status == 403
            assert_redacted(tech.evaluate('JSON.stringify(localStorage)'))
            tech_context.close()
            passed('imported technician changes initial password in browser; administrator history denied')

            orders = workbook('MOCK-orders-' + run + '.xlsx', [
                ['alarm_code', 'machine_id', 'assigned_to', 'source_record_id', 'source'],
                ['MOCK-' + run, machine['id'], user, run, 'batch-acceptance'],
                ['INVALID-' + run, machine['id'], 'missing_' + run, 'invalid-' + run, 'batch-acceptance'],
            ])
            page.locator('[data-admin-section-target="data"]').click()
            order_preview = preview(orders, 'work_orders')
            assert (order_preview['valid'], order_preview['skipped']) == (1, 1)
            with page.expect_response(lambda r: r.url == base + '/work-orders/import-excel') as response:
                page.locator('#adminExcelResult').get_by_role('button', name='確認匯入 1 筆有效工單').click()
            imported = response.value.json()
            assert imported['status'] == 'ok' and imported['imported'] == 1
            expect(page.locator('#adminExcelResult')).to_contain_text('匯入完成')
            assert preview(orders, 'work_orders')['valid'] == 0
            passed('work order assignee validation, confirmation and cross-batch deduplication')

            page.reload()
            expect(page.locator('#adminUserLabel')).to_contain_text('admin01')
            page.locator('[data-admin-section-target="data"]').click()
            history = page.locator('#adminBatchHistory')
            expect(history).to_contain_text(users.name)
            expect(history).to_contain_text(orders.name)
            history.locator('details').filter(has_text=user_batch).locator('summary').click()
            expect(history).to_contain_text('已新增 ' + user)
            detail = page.request.get(base + '/imports/batches/' + user_batch).json()['batch']
            assert_redacted(detail)
            assert all('values' not in row for row in detail['rows'])
            page.screenshot(path=str(output / '03-import-history.png'), full_page=True)
            passed('reloaded history shows source hash, actor, row errors and record IDs without passwords')
            report['batch_ids'] = [user_batch, imported['batch_id']]
            report['history_total'] = page.request.get(base + '/imports/batches').json()['total']
            assert not report['browser_errors']
            report['status'] = 'PASS'
        except Exception as exc:
            report['error'] = f'{type(exc).__name__}: {exc}'
            raise
        finally:
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            context.close()
            browser.close()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify(args.deployment.resolve(), args.output.resolve())
