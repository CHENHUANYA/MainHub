import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import fitz
import pytest

import app_context
import ingest
from bm25_text import tokenize_bm25
from rag_engine import AlarmRAGEngine
from rank_bm25 import BM25Okapi
from routes import chat_lookup_routes, ingest_routes
from services import company_config, prompt_profiles


@pytest.fixture
def compressor_settings(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "templates/company.compressor-demo.json").read_text(encoding="utf-8"))
    settings = {"company_config": config, "default_manual": "compressor_demo"}
    monkeypatch.setattr(company_config, "runtime_settings", lambda: settings)
    return settings


@pytest.fixture
def sop_pdf(tmp_path):
    path = tmp_path / "MOCK-compressor-SOP.pdf"
    with fitz.open() as doc:
        first = doc.new_page()
        first.insert_text((40, 40), "MOCK DATA - training only\nAIR-01 / E-42\n10\nRecord the pressure gauge reading.")
        second = doc.new_page()
        second.insert_text((40, 40), "MOCK DATA - escalation\nReport the observation to the maintenance team.")
        doc.save(path)
    return path


def test_text_parser_preserves_codes_short_lines_and_exact_pages(sop_pdf):
    sections = ingest.extract_document_sections(str(sop_pdf), "text_v1")
    assert len(sections) == 2
    assert [s["page"] for s in sections] == [1, 2]
    assert "AIR-01 / E-42\n10\n" in sections[0]["text"]
    assert "Report the observation" not in sections[0]["text"]
    assert all(s["code"] == "" and s["parser"] == "text_v1" for s in sections)


@pytest.mark.parametrize("budget", [
    {"max_chars": 10}, {"max_lines": 1}, {"max_sections": 1}, {"deadline": time.monotonic() - 1},
])
def test_text_parser_respects_each_extraction_budget(sop_pdf, budget):
    with pytest.raises(ingest.IngestBudgetExceeded):
        ingest.extract_document_sections(str(sop_pdf), "text_v1", **budget)


def test_text_parser_rejects_unknown_parser_and_invalid_window(sop_pdf):
    with pytest.raises(ValueError, match="Unknown PDF parser"):
        ingest.extract_document_sections(str(sop_pdf), "arbitrary.module")
    with pytest.raises(ValueError, match="chunk_size"):
        ingest.extract_text_chunks(str(sop_pdf), chunk_size=4, overlap=4)
    with pytest.raises(ValueError, match="no-general"):
        ingest.extract_document_sections(str(sop_pdf), "text_v1", include_general=False)


def test_configured_upload_and_cli_use_same_generic_parser(compressor_settings, sop_pdf, monkeypatch):
    engine = SimpleNamespace(sections=[])
    def add(sections):
        engine.sections.extend(sections)
        return len(sections)
    engine.add_sections = add
    monkeypatch.setattr(ingest_routes, "get_engine", lambda _name: engine)
    monkeypatch.setattr(ingest_routes, "ingest_log", [])
    with patch.object(ingest_routes, "append_jsonl"), patch.object(ingest_routes, "upsert_document_entry") as save:
        result = ingest_routes.ingest_pdf_file("compressor_demo", str(sop_pdf), sop_pdf.name, "hash", None)
    assert result["status"] == "ok" and result["alarms_added"] == 0 and result["general_added"] == 2
    assert save.call_args.args[1]["parser"] == "text_v1"
    for section in engine.sections:
        assert section["doc_id"] and section["section_id"] and section["locator"]
        assert section["source_file"] == sop_pdf.name
        assert section["collection"] == "compressor_demo"
    with patch.object(ingest, "find_document_by_hash", return_value=None), patch.object(ingest, "build_index") as build, patch.object(ingest, "upsert_document_entry"):
        assert ingest.main(["--pdf", str(sop_pdf), "--name", "compressor_demo"]) == 0
    assert [s["text"] for s in build.call_args.args[0]] == [s["text"] for s in engine.sections]


def test_scan_only_pdf_reports_ocr_without_creating_index(compressor_settings, tmp_path):
    pdf = tmp_path / "scan.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(pdf)
    with patch.object(ingest_routes, "get_engine") as get_engine:
        result = ingest_routes.ingest_pdf_file("compressor_demo", str(pdf), pdf.name, "hash", None)
    assert result["status"] == "error" and "OCR" in result["message"]
    get_engine.assert_not_called()


def test_generic_sop_retrieval_keeps_correct_source_and_page(compressor_settings, sop_pdf):
    sections = ingest.extract_document_sections(str(sop_pdf), "text_v1")
    sections = ingest.apply_doc_meta(sections, {"doc_id": "mock-sop", "filename": sop_pdf.name})
    sections.append({"text": "Unrelated document about office lighting", "code": "", "page": 9})
    engine = object.__new__(AlarmRAGEngine)
    engine.collection_name = "compressor_demo"
    engine.ready = True
    engine.sections = sections
    engine.bm25 = BM25Okapi([tokenize_bm25(section["text"]) for section in sections])
    engine.embedder = None
    docs = engine.retrieve("pressure gauge reading", top_k=1)
    assert len(docs) == 1 and docs[0]["meta"]["page"] == 1
    citation = app_context.build_rag_metadata("compressor_demo", "pressure gauge reading", docs)["citations"][0]
    assert citation["source_file"] == sop_pdf.name
    assert citation["doc_id"] == "mock-sop"


def test_generic_prompts_apply_to_single_and_multiturn_queries(compressor_settings):
    docs = [{"text": "MOCK DATA: record the reading.", "meta": {"source_file": "compressor.pdf", "page": 2}}]
    engine = SimpleNamespace(collection_name="compressor_demo", retrieve=lambda *_args, **_kwargs: docs)
    for history in [[], [app_context.Message(role="user", content="What is E-42?"), app_context.Message(role="assistant", content="Please provide evidence.")]]:
        messages, found = app_context.build_augmented_messages([*history, app_context.Message(role="user", content="How do I record the pressure?")], engine)
        assert "SINUMERIK" not in messages[0]["content"]
        assert "missing information" in messages[0]["content"]
        assert "actual filename and page" in messages[0]["content"]
        assert "compressor.pdf" in messages[-1]["content"] and "Page 2" in messages[-1]["content"]
        assert found == docs


def test_free_chat_uses_default_company_profile(compressor_settings):
    req = app_context.ChatRequest(messages=[app_context.Message(role="user", content="Explain maintenance")])
    with patch.object(chat_lookup_routes, "call_llm", new=AsyncMock(return_value="General explanation")) as call:
        asyncio.run(chat_lookup_routes.free_chat(req, actor={"user_id": "admin", "role": "admin"}))
    assert call.await_args.kwargs["messages"][0]["content"] == prompt_profiles.MAINTENANCE_FREE_CHAT


def test_generic_alarm_does_not_inherit_cnc_severity(compressor_settings):
    assert app_context.classify_alarm(3000, "compressor_demo")["severity"] == "info"
    with pytest.raises(ValueError, match="Unknown collection"):
        company_config.collection_config("808d")


def test_default_chat_selects_company_collection_and_rejects_unknown(compressor_settings):
    req = app_context.ChatRequest(messages=[app_context.Message(role="user", content="pressure")])
    actor = {"user_id": "admin", "role": "admin"}
    with patch.object(chat_lookup_routes, "limited_chat", new=AsyncMock(return_value={"ok": True})) as call:
        assert asyncio.run(chat_lookup_routes.chat_default(req, actor=actor)) == {"ok": True}
        assert call.await_args.args[1] == "compressor_demo"
        invalid = asyncio.run(chat_lookup_routes.chat_default(req, collection="808d", actor=actor))
        assert invalid["status"] == "error"
        assert call.await_count == 1


def test_cnc_prompt_keeps_legacy_format(monkeypatch):
    monkeypatch.setattr(company_config, "runtime_settings", lambda: {"default_manual": "808d"})
    assert "SINUMERIK" in prompt_profiles.prompts_for_collection("808d")["lookup"]
    assert "WORD FOR WORD" in prompt_profiles.prompts_for_collection("808d")["lookup"]


@pytest.mark.parametrize('question', [
    'CNC-01 的主軸鎖緊扭矩是多少 Nm？',
    'AIR-01 空壓機 E-42 的處理方式是什麼？',
    'Is the spindle rated for 3000 Nm?',
])
def test_general_cnc_questions_do_not_copy_an_unrelated_alarm(monkeypatch, question):
    monkeypatch.setattr(company_config, 'runtime_settings', lambda: {'default_manual': '808d'})
    engine = SimpleNamespace(collection_name='808d', retrieve=lambda *_args, **_kwargs: [])
    messages, _ = app_context.build_augmented_messages([app_context.Message(role='user', content=question)], engine)
    assert messages[0]['content'] == prompt_profiles.CHAT_SYSTEM_PROMPT


@pytest.mark.parametrize('question', ['3101', '3101, 3102', 'Alarm 3101', '請列出警報 3102 的文件資訊。'])
def test_explicit_cnc_alarm_lookups_keep_verbatim_mode(monkeypatch, question):
    monkeypatch.setattr(company_config, 'runtime_settings', lambda: {'default_manual': '808d'})
    engine = SimpleNamespace(collection_name='808d', retrieve=lambda *_args, **_kwargs: [])
    messages, _ = app_context.build_augmented_messages([app_context.Message(role='user', content=question)], engine)
    assert messages[0]['content'] == prompt_profiles.SYSTEM_PROMPT
