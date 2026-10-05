import asyncio
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import work_orders
from api_schemas import WorkOrderImportPreviewResponse
from tests.support.uploads import ADMIN, Upload, workbook_bytes as xlsx


def preview(content, actor=ADMIN):
    return asyncio.run(work_orders.preview_excel(Upload("orders.xlsx", content), actor=actor))


def confirm(content, token=None, actor=ADMIN):
    return asyncio.run(work_orders.import_excel(Upload("orders.xlsx", content), actor=actor, preview_token=token))


def test_preview_reports_normalized_rows_and_never_writes_orders(compressor_order_store):
    content = xlsx([
        ["alarm_code", "machine_id", "status", "root_cause", "repair_action", "verified_by", "notes", "resolution"],
        ["AIR-ALARM", "AIR-01", "verified", "leak", "replace seal", "someone", "historic note", "restored"],
        ["UNKNOWN", "missing", "pending"],
        ["DRAFT", "AIR-01", "pending", "", "", "", "retain draft note"],
    ])
    with patch.object(work_orders, "_save_orders") as save, patch.object(work_orders.postgres_work_orders, "save_one") as pg_save:
        result = preview(content)
    WorkOrderImportPreviewResponse.model_validate(result)
    assert result["valid"] == 2 and result["skipped"] == 1 and result["candidate_count"] == 1
    assert result["rows"][0]["values"]["manual"] == "compressor_demo"
    assert result["rows"][0]["values"]["status"] == "completed"
    assert len(result["rows"][0]["warnings"]) == 2
    assert "Unknown machine" in result["rows"][1]["error"]
    assert result["rows"][2]["values"]["notes"] == "retain draft note"
    save.assert_not_called()
    pg_save.assert_not_called()
    assert not Path(work_orders.WO_FILE).exists()


@pytest.mark.parametrize("change", ["file", "settings", "orders", "actor", "missing_token"])
def test_confirmation_rejects_changed_preview_without_writing(compressor_order_store, change):
    content = xlsx([["alarm_code", "machine_id"], ["AIR-LOW", "AIR-01"]])
    token = preview(content)["preview_token"]
    actor = ADMIN
    if change == "file":
        content = xlsx([["alarm_code"], ["different"]])
    elif change == "settings":
        compressor_order_store["revision"] = "changed"
    elif change == "orders":
        work_orders._save_orders([work_orders._build_order_dict("existing", manual="compressor_demo")])
    elif change == "actor":
        actor = {**ADMIN, "user_id": "another-admin"}
    else:
        token = None
    before = work_orders._load_orders()
    result = confirm(content, token, actor)
    assert result["status"] == "error"
    assert work_orders._load_orders() == before


def test_confirmation_only_imports_valid_rows_and_same_token_cannot_repeat(compressor_order_store):
    content = xlsx([["alarm_code", "machine_id", "priority"], ["OK", "AIR-01", "high"], ["BAD", "AIR-01", "typo"]])
    token = preview(content)["preview_token"]

    async def simultaneous():
        return await asyncio.gather(*(
            work_orders.import_excel(Upload("orders.xlsx", content), actor=ADMIN, preview_token=token) for _ in range(2)
        ))

    results = asyncio.run(simultaneous())
    assert sorted(result["status"] for result in results) == ["error", "ok"]
    success = next(result for result in results if result["status"] == "ok")
    assert success["imported"] == 1 and success["skipped"] == 1
    assert [order["alarm_code"] for order in work_orders._load_orders()] == ["OK"]


@pytest.mark.parametrize("header,row,message", [
    (["alarm_code", "priority"], ["A", "urgent"], "Unknown priority"),
    (["alarm_code", "status"], ["A", "done"], "Unknown status"),
    (["alarm_code", "description"], ["", "missing code"], "alarm_code is required"),
    (["alarm_code", "manual"], ["A", "other"], "Unknown collection"),
    (["alarm_code", "machine_id", "manual"], ["A", "AIR-01", "other"], "Manual conflicts"),
])
def test_invalid_rows_are_explicit_and_all_invalid_batch_cannot_commit(compressor_order_store, header, row, message):
    content = xlsx([header, row])
    result = preview(content)
    assert result["valid"] == 0 and result["skipped"] == 1
    assert message in result["rows"][0]["error"]
    assert confirm(content, result["preview_token"])["status"] == "error"
    assert not Path(work_orders.WO_FILE).exists()


@pytest.mark.parametrize("rows", [
    [["alarm_code", "code"], ["A", "B"]],
    [["description"], ["no alarm column"]],
    [["alarm_code"]] + [[str(i)] for i in range(1001)],
    [[str(i) for i in range(33)]],
])
def test_invalid_shape_is_rejected_before_commit(compressor_order_store, rows):
    assert preview(xlsx(rows))["status"] == "error"
    assert not Path(work_orders.WO_FILE).exists()


def test_atomic_json_failure_keeps_existing_orders(compressor_order_store, monkeypatch):
    work_orders._save_orders([work_orders._build_order_dict("existing", manual="compressor_demo")])
    before = Path(work_orders.WO_FILE).read_bytes()
    content = xlsx([["alarm_code"], ["A"], ["B"]])
    token = preview(content)["preview_token"]
    monkeypatch.setattr(work_orders, "_save_orders", Mock(side_effect=OSError("disk full")))
    assert confirm(content, token) == {"status": "error", "message": "disk full"}
    assert Path(work_orders.WO_FILE).read_bytes() == before


def test_multipart_routes_enforce_admin_and_confirmation_contract(compressor_order_store):
    app = FastAPI()
    app.include_router(work_orders.router)
    app.dependency_overrides[work_orders.get_actor] = lambda: ADMIN
    content = xlsx([["alarm_code"], ["AIR-A"]])
    with TestClient(app) as client:
        files = {"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        result = client.post("/work-orders/import-excel/preview", files=files).json()
        WorkOrderImportPreviewResponse.model_validate(result)
        assert client.post("/work-orders/import-excel", files=files).json()["status"] == "error"
        result = client.post("/work-orders/import-excel", files=files, data={"preview_token": result["preview_token"]}).json()
        assert result["imported"] == 1
        app.dependency_overrides[work_orders.get_actor] = lambda: {**ADMIN, "role": "operator"}
        for path in ("/work-orders/import-excel/preview", "/work-orders/import-excel"):
            assert client.post(path, files=files).json()["message"] == "Permission denied"
