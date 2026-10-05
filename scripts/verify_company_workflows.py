"""Verify two isolated MOCK DATA workflows using JSON storage and real BM25 indexes.

Does not call Ollama, PostgreSQL or Qdrant. Actor objects stand in for authenticated
sessions; the production route functions still enforce roles and line permissions.
Every run requires a new output directory and preserves its evidence for review.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCENARIOS = ("cnc", "compressor")


def fingerprint() -> str:
    from scripts.export_company_template import bundle_files
    digest = hashlib.sha256()
    for path in bundle_files():
        if path.suffix in {".py", ".js", ".json"}:
            digest.update(path.relative_to(ROOT).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def runtime_snapshot(directory: Path) -> dict[str, str]:
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*")) if path.is_file()}


class OfflineVectorStore:
    """No vector operations: this verification exercises the BM25 fallback."""
    def ensure_collection(self, _name):
        pass

    def delete_collection(self, _name):
        pass

    def count(self, _name):
        return 0


async def exercise_company(name: str, output: Path) -> dict:
    # This must happen before importing any runtime modules that capture paths.
    runtime = output / "runtime"
    os.environ.update({
        "DATA_STORE": "json", "DB_PATH": str(runtime), "ALARM_RAG_ENV": "development",
        "ADMIN_INITIAL_PASSWORD": secrets.token_urlsafe(24), "ADMIN_INITIAL_PASSWORD_FILE": "",
        "ALARM_RAG_INDEX_SIGNING_KEY": secrets.token_hex(32), "ALARM_RAG_INDEX_SIGNING_KEY_FILE": "",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "RAG_HF_LOCAL_ONLY": "true",
    })
    import fitz
    import auth
    import app_context
    import issues
    import rag_engine
    import work_orders
    from routes import ingest_routes, settings_routes, chat_lookup_routes
    from services.company_config import CompanyConfig, runtime_settings
    from services.prompt_profiles import prompts_for_collection

    checks = []
    def require(condition: bool, label: str) -> None:
        if not condition:
            raise AssertionError(label)
        checks.append(label)

    def ok(result: dict, label: str) -> dict:
        require(result.get("status") == "ok", f"{label}: {result.get('message', 'ok')}")
        return result

    started = time.monotonic()
    config = CompanyConfig.model_validate_json((ROOT / "templates" / f"company.{name}-demo.json").read_text(encoding="utf-8"))
    machine = config.machines[0]
    collection = machine.collection
    other = "compressor_demo" if name == "cnc" else "cnc_manual"
    admin = {"user_id": "admin01", "role": "admin", "line_scope": ["*"]}
    request = settings_routes.CompanyImport(config=config)
    preview = ok(await settings_routes.preview_company_config(request, actor=admin), "config preview")
    require(not (runtime / "system_settings.json").exists(), "preview does not write settings")
    request.expected_revision = preview["expected_revision"]
    ok(await settings_routes.apply_company_config(request, actor=admin), "config apply")
    require(runtime_settings()["default_manual"] == collection, "company default persists")
    stale = await settings_routes.apply_company_config(request, actor=admin)
    require(stale["status"] == "error", "stale company config rejected")

    actors = {}
    for role in ("operator", "maintenance", "supervisor"):
        user_id = f"{name}_{role}"
        result = ok(await auth.api_create_user(auth.CreateUserRequest(
            user_id=user_id, name=f"MOCK {role}", role=role, line_scope=[machine.line_id],
            password=secrets.token_urlsafe(24),
        ), actor=admin), f"create {role}")
        actors[role] = {**result["user"], "user_id": user_id}
    operator, maintenance, supervisor = (actors[role] for role in ("operator", "maintenance", "supervisor"))
    outsider = {"user_id": "outside", "role": "operator", "line_scope": ["unrelated-line"]}
    catalog = ok(await settings_routes.get_company_config(actor=operator), "role catalog")
    require([item["id"] for item in catalog["machines"]] == [machine.id], "configured machine visible")
    hidden = await settings_routes.get_company_config(actor=outsider)
    require(hidden["machines"] == [], "out-of-scope machine hidden")

    pdf = output / f"MOCK-{name}.pdf"
    with fitz.open() as document:
        page = document.new_page()
        text = ("3000\nMOCK training observation\nRecord the gauge reading.\nReport to maintenance."
                if name == "cnc" else "MOCK DATA - training only\nAIR-01 / E-42\nRecord the gauge reading.\nReport to maintenance.")
        page.insert_text((40, 40), text)
        for topic in ("Office lighting", "Training attendance"):
            page = document.new_page()
            page.insert_text((40, 40), f"MOCK DATA\n{topic}\nUnrelated demonstration content.")
        document.save(pdf)

    # No loaded embedding/reranker models or external vector backend in this mode.
    with patch.object(rag_engine, "_try_get_models", return_value=(None, None)), patch.object(rag_engine, "get_store", return_value=OfflineVectorStore()):
        result = ok(ingest_routes.ingest_pdf_file(collection, str(pdf), pdf.name,
            hashlib.sha256(pdf.read_bytes()).hexdigest(), None), "PDF import")
        engine = app_context.get_engine(collection)
        docs = engine.retrieve("gauge reading", top_k=1)
        require(bool(docs) and docs[0]["meta"]["page"] == 1, "query retrieves source page")
        require(docs[0]["meta"]["doc_id"] == result["doc_id"], "query retrieves own document")
        require(prompts_for_collection(collection)["lookup"].find("SINUMERIK") >= 0 if name == "cnc"
                else "SINUMERIK" not in prompts_for_collection(collection)["lookup"], "company prompt selected")
        require(chat_lookup_routes.validate_collection_name(other) is not None, "other company collection rejected")
        denied = await issues.api_create_issue(issues.CreateIssue(machine_id=machine.id, description="MOCK"), actor=outsider)
        require(denied["status"] == "error", "out-of-scope issue denied")
        created = ok(await issues.api_create_issue(issues.CreateIssue(
            machine_id=machine.id, alarm_code="3000" if name == "cnc" else "E-42",
            description=f"MOCK DATA {name}: gauge observation", source="mock-demo",
        ), actor=operator), "issue creation")
        issue = created["issue"]
        require(issue["manual"] == collection and issue["line_id"] == machine.line_id, "issue resolves machine mapping")
        escalated = ok(await issues.api_escalate_issue(issue["issue_id"], actor=supervisor), "escalation")
        order = escalated["work_order"]
        again = ok(await issues.api_escalate_issue(issue["issue_id"], actor=supervisor), "repeat escalation")
        require(again["created"] is False and again["work_order_id"] == order["id"], "escalation creates no duplicate")
        require(order["manual"] == collection and order["machine_id"] == machine.id, "work order mapping preserved")

        invalid = await work_orders.api_update_order(order["id"], work_orders.UpdateWorkOrder(
            machine_id="UNREGISTERED", version=order["version"]), actor=supervisor)
        require(invalid["status"] == "error", "unknown machine edit rejected")
        current_issue = issues.get_issue_dict(issue["issue_id"])
        invalid = await issues.api_update_issue(issue["issue_id"], issues.UpdateIssue(
            line_id="unregistered-line", version=current_issue["version"]), actor=supervisor)
        require(invalid["status"] == "error", "invalid issue line edit rejected")

        for actor, changes in [
            (supervisor, {"status": "assigned", "assigned_to": maintenance["user_id"]}),
            (maintenance, {"status": "in_progress"}),
            (maintenance, {"status": "completed", "root_cause": f"MOCK {name} training condition",
                "repair_action": "MOCK recorded observation", "resolution": "MOCK training complete"}),
            (operator, {"status": "verified"}),
        ]:
            result = ok(await work_orders.api_update_order(order["id"], work_orders.UpdateWorkOrder(
                **changes, version=order["version"]), actor=actor), f"work order {changes['status']}")
            order = result["order"]
        require(issues.get_issue_dict(issue["issue_id"])["status"] == "verified", "issue follows work order closure")
        require(order["kb_review_status"] == "pending_review", "knowledge waits for approval")
        denied = await work_orders.review_work_order_knowledge(order["id"], work_orders.KnowledgeReviewRequest(
            action="approve", version=order["version"]), actor=maintenance)
        require(denied["status"] == "error", "maintenance cannot approve knowledge")
        review = ok(await work_orders.review_work_order_knowledge(order["id"], work_orders.KnowledgeReviewRequest(
            action="approve", version=order["version"]), actor=admin), "admin knowledge approval")
        require(review["order"]["kb_review_status"] == "ingested", "approved knowledge indexed")
        require(review["ingest"]["collection"] == collection, "knowledge enters own collection")
        require(review["ingest"]["validation"]["retrieval_hit"], "approved knowledge retrievable")
        current_issue = issues.get_issue_dict(issue["issue_id"])
        reopen = await issues.api_update_issue(issue["issue_id"], issues.UpdateIssue(
            status="open", operator_note="MOCK repeat observation", version=current_issue["version"]), actor=operator)
        require(reopen["status"] == "error" and "disabled" in reopen["message"], "company reopen policy enforced")
        # Load from the signed on-disk index in a new engine, not just memory.
        reloaded = rag_engine.AlarmRAGEngine(collection)
        require(any(section.get("doc_id") == review["ingest"]["doc_id"] for section in reloaded.sections), "knowledge persists after engine reload")
        require(not (runtime / f"bm25_{other}.pkl").exists(), "no other company index created")

    return {"status": "pass", "scenario": name, "company": config.company.id,
        "collection": collection, "machine": machine.id, "checks": checks,
        "elapsed_seconds": round(time.monotonic() - started, 2), "source_fingerprint": fingerprint(),
        "issue_id": issue["issue_id"], "work_order_id": order["id"], "knowledge_doc_id": review["ingest"]["doc_id"],
        "mode": "MOCK DATA; JSON; real PDF/BM25; direct route calls; simulated actors; no LLM/vector inference"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new evidence directory; existing paths are refused")
    parser.add_argument("--scenario", choices=SCENARIOS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.scenario:
        output.mkdir(parents=True, exist_ok=False)
        try:
            report = asyncio.run(exercise_company(args.scenario, output))
        except Exception as exc:
            if not output.is_dir():
                raise
            report = {"status": "fail", "scenario": args.scenario, "error": f"{type(exc).__name__}: {exc}"}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if report["status"] == "pass" else 1
    output.mkdir(parents=True, exist_ok=False)
    reports = []
    first_snapshot = {}
    for name in SCENARIOS:
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--scenario", name,
            "--output", str(output / name)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}, timeout=180)
        (output / f"{name}.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        report_path = output / name / "report.json"
        reports.append(json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists()
            else {"status": "fail", "scenario": name, "error": "worker did not produce a report"})
        if name == SCENARIOS[0]:
            first_snapshot = runtime_snapshot(output / name / "runtime")
    passed = all(report["status"] == "pass" for report in reports)
    same_core = passed and len({report["source_fingerprint"] for report in reports}) == 1
    isolated = bool(first_snapshot) and first_snapshot == runtime_snapshot(output / SCENARIOS[0] / "runtime")
    summary = {"status": "pass" if passed and same_core and isolated else "fail", "same_core": same_core,
        "first_runtime_unchanged_after_second": isolated, "scenarios": reports,
        "not_verified": ["Ollama/Gemma 4 answers", "embedding/vector retrieval", "browser/login sessions", "PostgreSQL/Docker isolation", "real equipment instructions"],
        "timing_note": "Automated run time only; not company onboarding labor time."}
    (output / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{summary['status'].upper()}: {output / 'report.json'}")
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
