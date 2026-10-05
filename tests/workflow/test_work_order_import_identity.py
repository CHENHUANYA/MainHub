import asyncio

import pytest

import work_orders
from tests.support.uploads import ADMIN, Upload, workbook_bytes


def preview(rows):
    content = workbook_bytes(rows)
    result = asyncio.run(work_orders.preview_excel(Upload("history.xlsx", content), actor=ADMIN))
    assert result["status"] == "ok"
    return content, result


def confirm(content, token):
    return asyncio.run(work_orders.import_excel(
        Upload("history.xlsx", content), actor=ADMIN, preview_token=token,
    ))


@pytest.mark.parametrize("account,error", [
    ({}, "Unknown assigned_to"),
    ({"user_id": "tech", "role": "maintenance", "active": False}, "Inactive assigned_to"),
    ({"user_id": "tech", "role": "operator", "active": True}, "must be a maintenance"),
])
def test_assignee_errors_are_visible_before_commit(compressor_order_store, monkeypatch, account, error):
    monkeypatch.setattr(work_orders, "resolve_user", lambda key: account)
    content, result = preview([["alarm_code", "assigned_to"], ["A", "tech"]])
    assert result["valid"] == 0
    assert error in result["rows"][0]["error"]
    assert confirm(content, result["preview_token"])["status"] == "error"
    assert work_orders._load_orders() == []


@pytest.mark.parametrize("change", ["disabled", "deleted", "role"])
def test_account_change_invalidates_preview(compressor_order_store, monkeypatch, change):
    account = {"user_id": "tech", "role": "maintenance", "active": True}
    monkeypatch.setattr(work_orders, "resolve_user", lambda key: account)
    content, result = preview([["alarm_code", "assigned_to"], ["A", "tech"]])
    assert result["rows"][0]["values"]["status"] == "assigned"
    if change == "disabled":
        account["active"] = False
    elif change == "deleted":
        account.clear()
    else:
        account["role"] = "operator"
    assert "Preview again" in confirm(content, result["preview_token"])["message"]
    assert work_orders._load_orders() == []


def test_reordered_batches_and_same_batch_duplicates_are_skipped(compressor_order_store):
    content, result = preview([["alarm_code", "machine_id"], ["A", "AIR-01"], ["A", "AIR-01"]])
    assert (result["valid"], result["skipped"]) == (1, 1)
    assert "Duplicate import record: row 2" in result["rows"][1]["error"]
    assert confirm(content, result["preview_token"])["imported"] == 1
    stored = work_orders._load_orders()[0]
    content, result = preview([["machine_id", "alarm_code", "priority"], [" AIR-01 ", " A ", "MEDIUM"], ["AIR-01", "B"]])
    assert (result["valid"], result["skipped"]) == (1, 1)
    assert stored["id"] in result["rows"][0]["error"]
    assert confirm(content, result["preview_token"])["imported"] == 1
    assert len(work_orders._load_orders()) == 2


def test_import_identity_survives_edits_and_soft_deletion(compressor_order_store):
    rows = [["alarm_code", "description"], ["A", "original"]]
    content, result = preview(rows)
    assert confirm(content, result["preview_token"])["imported"] == 1
    orders = work_orders._load_orders()
    orders[0].update(description="updated", status="cancelled", deleted_at="2026-09-23T00:00:00")
    work_orders._save_orders(orders)
    content, result = preview(rows)
    assert result["valid"] == 0
    assert confirm(content, result["preview_token"])["status"] == "error"
    assert len(work_orders._load_orders()) == 1


def test_source_ids_distinguish_incidents_and_detect_changed_reimports(compressor_order_store):
    header = ["alarm_code", "source", "source_record_id", "description"]
    content, result = preview([header, ["A", "legacy", "1", "same"], ["A", "legacy", "2", "same"]])
    assert confirm(content, result["preview_token"])["imported"] == 2
    content, result = preview([header, ["B", "legacy", "1", "changed"], ["B", "another-system", "1", "changed"]])
    assert result["valid"] == 1 and result["skipped"] == 1
    assert confirm(content, result["preview_token"])["imported"] == 1
    meta = work_orders._load_orders()[0]["import_metadata"]
    assert meta["source_record_id"] == "1"
    assert meta["row"] == 3 and meta["imported_by"] == ADMIN["user_id"]
    assert len(meta["file_sha256"]) == 64


def test_valid_assignee_is_preserved(compressor_order_store, monkeypatch):
    monkeypatch.setattr(work_orders, "resolve_user", lambda key: {
        "user_id": key, "role": "maintenance", "active": True,
    })
    content, result = preview([["alarm_code", "assigned_to"], ["A", "tech"]])
    assert confirm(content, result["preview_token"])["imported"] == 1
    order = work_orders._load_orders()[0]
    assert order["assigned_to"] == "tech" and order["status"] == "assigned"
