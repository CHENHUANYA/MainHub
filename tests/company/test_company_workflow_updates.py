import asyncio
import copy
import json
from pathlib import Path

import pytest

import issues
import work_orders
from services import company_config


@pytest.fixture
def company_records(tmp_path, monkeypatch):
    config = json.loads((Path(__file__).resolve().parents[2] / "templates/company.compressor-demo.json").read_text(encoding="utf-8"))
    config["collections"].append({**config["collections"][0], "id": "other_manual"})
    config["lines"].append({"id": "other-line", "display_name": "Other line"})
    config["machines"].extend([
        {"id": "AIR-02", "display_name": "Second", "line_id": "utilities", "collection": "compressor_demo"},
        {"id": "AIR-03", "display_name": "Other KB", "line_id": "utilities", "collection": "other_manual"},
        {"id": "AIR-04", "display_name": "Other line", "line_id": "other-line", "collection": "compressor_demo"},
    ])
    monkeypatch.setattr(company_config, "runtime_settings", lambda: {"company_config": config, "default_manual": "compressor_demo"})
    monkeypatch.setenv("DATA_STORE", "json")
    monkeypatch.setattr(issues, "DB_DIR", str(tmp_path))
    monkeypatch.setattr(issues, "ISSUE_FILE", str(tmp_path / "issues.json"))
    monkeypatch.setattr(work_orders, "DB_DIR", str(tmp_path))
    monkeypatch.setattr(work_orders, "WO_FILE", str(tmp_path / "work_orders.json"))
    issue = issues.create_issue_dict(machine_id="AIR-01", line_id="utilities", manual="compressor_demo", description="MOCK")
    order = work_orders.create_order_dict(alarm_code="E-42", machine_id="AIR-01", manual="compressor_demo", description="MOCK")
    actor = {"user_id": "supervisor", "role": "supervisor", "line_scope": ["utilities"]}
    return issue, order, actor


@pytest.mark.parametrize("machine", ["UNKNOWN", "AIR-03", "AIR-04"])
def test_work_order_edit_cannot_break_mapping_or_line_scope(company_records, machine):
    _, order, actor = company_records
    before = copy.deepcopy(work_orders.get_order_dict(order["id"]))
    result = asyncio.run(work_orders.api_update_order(order["id"], work_orders.UpdateWorkOrder(
        machine_id=machine, version=order["version"]), actor=actor))
    assert result["status"] == "error"
    assert work_orders.get_order_dict(order["id"]) == before


@pytest.mark.parametrize("fields", [
    {"machine_id": "UNKNOWN"}, {"machine_id": "AIR-03"}, {"line_id": "other-line"},
    {"machine_id": "AIR-04", "line_id": "other-line"},
])
def test_issue_edit_cannot_break_mapping_or_line_scope(company_records, fields):
    issue, _, actor = company_records
    before = copy.deepcopy(issues.get_issue_dict(issue["issue_id"]))
    result = asyncio.run(issues.api_update_issue(issue["issue_id"], issues.UpdateIssue(
        **fields, version=issue["version"]), actor=actor))
    assert result["status"] == "error"
    assert issues.get_issue_dict(issue["issue_id"]) == before


def test_valid_same_line_and_collection_machine_edit_still_works(company_records):
    issue, order, actor = company_records
    changed_issue = asyncio.run(issues.api_update_issue(issue["issue_id"], issues.UpdateIssue(
        machine_id="AIR-02", version=issue["version"]), actor=actor))
    changed_order = asyncio.run(work_orders.api_update_order(order["id"], work_orders.UpdateWorkOrder(
        machine_id="AIR-02", version=order["version"]), actor=actor))
    assert changed_issue["status"] == changed_order["status"] == "ok"
    assert changed_issue["issue"]["manual"] == changed_order["order"]["manual"] == "compressor_demo"


def test_unrelated_edits_do_not_revalidate_retired_historical_mapping(company_records):
    issue, order, actor = company_records
    issue["manual"] = order["manual"] = "retired_manual"
    issue["machine_id"] = order["machine_id"] = "retired_machine"
    issues._save_issues([issue])
    work_orders._save_orders([order])
    result = asyncio.run(work_orders.api_update_order(order["id"], work_orders.UpdateWorkOrder(
        priority="high", version=order["version"]), actor=actor))
    assert result["status"] == "ok" and result["order"]["manual"] == "retired_manual"
    result = asyncio.run(issues.api_update_issue(issue["issue_id"], issues.UpdateIssue(
        severity="high", version=issue["version"]), actor=actor))
    assert result["status"] == "ok" and result["issue"]["manual"] == "retired_manual"
