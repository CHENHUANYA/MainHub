from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

import auth
import work_orders


TECH = {"user_id": "tech01", "role": "maintenance", "line_scope": ["*"]}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def returned_order(compressor_order_store, monkeypatch):
    monkeypatch.setattr(work_orders, "_is_operator_or_supervisor", lambda user: user == "supervisor01")
    order = work_orders.create_order_dict(alarm_code="TEST", manual="compressor_demo", assigned_to="tech01")
    order.update(status="verified", verified_by="supervisor01", completed_by="tech01",
                 accepted_by="tech01", completed_at="2026-09-27T10:00:00", kb_review_status="needs_revision",
                 kb_review_note="Add inspection steps", root_cause="Mock cause", repair_action="Mock steps",
                 resolution="Mock result", kb_candidate=True)
    work_orders._save_orders([order])
    return order


@pytest.mark.anyio
async def test_assigned_technician_can_see_and_resubmit_returned_record(returned_order, monkeypatch):
    ingest = AsyncMock()
    monkeypatch.setattr(work_orders, "_auto_feedback_to_kb", ingest)
    page = await work_orders.api_page_orders(limit=50, actor=TECH)
    assert [o["id"] for o in page["orders"]] == [returned_order["id"]]
    result = await work_orders.api_update_order(returned_order["id"], work_orders.UpdateWorkOrder(
        repair_action="Mock steps with inspection detail", version=returned_order["version"]), actor=TECH)
    assert result["status"] == "ok", result
    saved = result["order"]
    assert saved["kb_review_status"] == "pending_review"
    for key in ("status", "verified_by", "completed_by", "accepted_by", "completed_at", "assigned_to", "kb_review_note"):
        assert saved[key] == returned_order[key]
    assert saved["version"] == returned_order["version"] + 1
    assert saved["updated_by"] == "tech01"
    assert "kb_review_status" in saved["work_order_history"][-1]["fields"]
    ingest.assert_not_awaited()
    # The one-time exception closes as soon as it is sent for review.
    retry = await work_orders.api_update_order(saved["id"], work_orders.UpdateWorkOrder(
        notes="Edit after resubmission", version=saved["version"]), actor=TECH)
    assert retry["status"] == "error"


@pytest.mark.parametrize("changes", [
    {"assigned_to": "other"}, {"assigned_to": ""}, {"status": "cancelled"},
    {"kb_review_status": "pending_review"}, {"kb_review_status": "ingested"},
    {"kb_review_status": "rejected"}, {"deleted_at": "2026-09-27"},
])
def test_revision_visibility_remains_narrow(returned_order, changes):
    order = {**returned_order, **changes}
    assert not auth.can_view_work_order(TECH, order)
    assert not auth.can_revise_work_order_knowledge(TECH, order)


@pytest.mark.anyio
@pytest.mark.parametrize("fields", [
    {"status": "in_progress"}, {"status": "verified"}, {"assigned_to": "other"},
    {"priority": "high"}, {"machine_id": "other"}, {"description": "rewrite"},
    {"verified_by": "tech01"}, {"kb_candidate": True}, {"resolution": " "},
    {"root_cause": ""}, {"notes": ""},
])
async def test_revision_rejects_workflow_changes_and_invalid_supplements(returned_order, fields):
    before = deepcopy(work_orders.get_order_dict(returned_order["id"]))
    result = await work_orders.api_update_order(returned_order["id"], work_orders.UpdateWorkOrder(
        **fields, version=returned_order["version"]), actor=TECH)
    assert result["status"] == "error", result
    assert work_orders.get_order_dict(returned_order["id"]) == before


@pytest.mark.anyio
@pytest.mark.parametrize("version", [None, 0])
async def test_revision_requires_current_version(returned_order, version):
    before = deepcopy(work_orders.get_order_dict(returned_order["id"]))
    result = await work_orders.api_update_order(returned_order["id"], work_orders.UpdateWorkOrder(
        notes="More detail", version=version), actor=TECH)
    assert result["status"] == "error"
    assert work_orders.get_order_dict(returned_order["id"]) == before


@pytest.mark.anyio
async def test_completed_returned_record_can_be_supplemented(returned_order):
    returned_order["status"] = "completed"
    returned_order["verified_by"] = ""
    work_orders._save_orders([returned_order])
    result = await work_orders.api_update_order(returned_order["id"], work_orders.UpdateWorkOrder(
        notes="Inspection details", version=returned_order["version"]), actor=TECH)
    assert result["status"] == "ok"
    assert result["order"]["status"] == "completed"
    assert result["order"]["kb_review_status"] == "pending_review"
