"""Optional headless Edge checks against isolated FastAPI import routes."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import work_orders
from tests.support.uploads import ADMIN, workbook_bytes as xlsx


@pytest.mark.parametrize("entry", ["admin", "operations"])
def test_excel_preview_cancel_and_confirm_in_browser(compressor_order_store, tmp_path, entry):
    playwright = pytest.importorskip("playwright.sync_api")
    app = FastAPI()
    app.include_router(work_orders.router)
    app.dependency_overrides[work_orders.get_actor] = lambda: ADMIN
    root = Path(__file__).resolve().parents[2]
    requests = []
    with TestClient(app) as client, playwright.sync_playwright() as runner:
        try:
            browser = runner.chromium.launch(channel="msedge", headless=True)
        except playwright.Error as exc:
            pytest.skip(f"Headless Edge unavailable: {exc}")
        try:
            page = browser.new_page(viewport={"width": 900, "height": 750})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def route_request(route):
                request = route.request
                path = request.url.removeprefix("http://preview.local")
                requests.append(path)
                response = client.request(
                    request.method, path, content=request.post_data_buffer,
                    headers={"content-type": request.headers.get("content-type", "")},
                )
                route.fulfill(status=response.status_code, content_type="application/json", body=response.content)

            page.route("http://preview.local/**", route_request)
            result_id = "adminExcelResult" if entry == "admin" else "excelResult"
            page.set_content(f'<input id="file" type="file"><div id="{result_id}" aria-live="polite"></div>')
            page.add_style_tag(path=str(root / "static/css/excel-import.css"))
            page.evaluate("""() => {
              window.AlarmApp = {
                $: id => document.getElementById(id),
                apiJson: async (path, options) => (await fetch('http://preview.local' + path, options)).json(),
                formatError: error => error.message,
              };
            }""")
            entry_script = "static/js/pages/admin.js" if entry == "admin" else "static/js/modules/operations.js"
            page.add_script_tag(path=str(root / entry_script))
            page.add_script_tag(path=str(root / "static/js/modules/excel-import.js"))
            page.evaluate("""entry => {
              window.loadAdminConsole = window.loadWorkOrders = async () => { throw new Error('refresh failed'); };
              document.getElementById('file').addEventListener('change', event => {
                (entry === 'admin' ? window.uploadAdminExcel : window.uploadExcel)(event.target);
              });
            }""", entry)
            content = xlsx([
                ["alarm_code", "machine_id", "description"],
                ["AIR-LOW", "AIR-01", '<img src=x onerror="window.injected=true">'],
                ["INVALID", "missing", "wrong mapping"],
            ])
            upload = {"name": "mock-history.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": content}
            page.locator("#file").set_input_files(upload)
            confirm = page.get_by_role("button", name="確認匯入 1 筆有效工單")
            confirm.wait_for()
            assert requests == ["/work-orders/import-excel/preview"]
            assert not Path(work_orders.WO_FILE).exists()
            page.locator("summary").first.click()
            assert page.locator("img").count() == 0
            assert page.evaluate("window.injected || false") is False
            assert "Unknown machine" in page.locator(f"#{result_id}").inner_text()
            page.screenshot(path=str(tmp_path / f"{entry}-preview.png"), full_page=True)
            page.get_by_role("button", name="取消", exact=True).click()
            assert not Path(work_orders.WO_FILE).exists()
            page.locator("#file").set_input_files(upload)
            confirm.click()
            page.get_by_text("工單已匯入，畫面更新失敗，請重新整理。").wait_for()
            assert len(work_orders._load_orders()) == 1
            assert requests.count("/work-orders/import-excel") == 1
            assert page.locator("#file").is_enabled()
            assert "匯入完成：新增 1 筆，略過 1 筆" in page.locator(f"#{result_id}").inner_text()
            assert not errors
        finally:
            browser.close()
