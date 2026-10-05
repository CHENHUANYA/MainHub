import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app_context import ChatRequest, Message
from routes import chat_lookup_routes
from services.evidence_guard import missing_requested_identifiers, mock_evidence_notice


DOCS = [{'text': 'MOCK DATA\nAIR-01 / E-42\nRecord the gauge reading. Report to maintenance.',
         'meta': {'source_file': 'MOCK-compressor.pdf', 'page': 1}}]


@pytest.mark.parametrize('question,missing', [
    ('AIR-01 的 E-99 原因與處理方式？', ['E-99']),
    ('CNC-01 警報 3101 的原因？', ['CNC-01', '3101']),
    ('AIR-01 / E-42: what should be recorded?', []),
    ('air-01 / e-42', []),
    ('What is E-4?', ['E-4']),
    ('E-99 and e-99', ['E-99']),
    ('What is the pressure limit in bar?', []),
    ('Is 3000 Nm specified?', []),
    ('Report within 300 minutes; alarm code E-42', []),
    ('Read AIR-99.pdf and summarize its gauge instructions.', []),
    ('Check E-99. What does it mean?', ['E-99']),
    ('Alarm 3101', ['3101']),
    ('3101?', ['3101']),
    ('3101, 3999', ['3101', '3999']),
    ('3101、3999？', ['3101', '3999']),
    ('3101 / 3999', ['3101', '3999']),
    ('3101 3999', ['3101', '3999']),
    ('3101, 3101', ['3101']),
    ('Use 3101, 3999 Nm?', []),
])
def test_only_explicit_identifiers_require_exact_evidence(question, missing):
    assert missing_requested_identifiers(question, DOCS) == missing


def test_metadata_code_counts_but_filename_does_not_prove_identifier():
    assert missing_requested_identifiers('alarm 3101', [{'text': '', 'meta': {'code': '3101'}}]) == []
    docs = [{'text': 'No matching content', 'meta': {'source_file': 'CNC-01.pdf', 'page': 1}}]
    assert missing_requested_identifiers('CNC-01', docs) == ['CNC-01']


def test_numeric_lookup_list_checks_each_requested_code():
    docs = [{'text': 'Training observation', 'meta': {'code': '3101'}}]
    assert missing_requested_identifiers('3101, 3999', docs) == ['3999']


def test_separate_identifiers_are_necessary_evidence_not_proof_of_relationship():
    docs = [{'text': 'AIR-01 training attendance.', 'meta': {}},
            {'text': 'AIR-02 / E-42: record the gauge reading.', 'meta': {}}]
    # This lexical guard does not establish which equipment owns the procedure.
    # Prompts and semantic review must still reject borrowing AIR-02 instructions.
    assert missing_requested_identifiers('AIR-01 / E-42', docs) == []


def test_company_mapping_does_not_make_generic_manual_equipment_evidence(monkeypatch):
    from services import company_config
    from pathlib import Path
    config = json.loads((Path(__file__).resolve().parents[2] /
        'templates/company.compressor-demo.json').read_text(encoding='utf-8'))
    monkeypatch.setattr(company_config, 'runtime_settings', lambda: {'company_config': config})
    assert company_config.collection_config('compressor_demo').parser == 'text_v1'
    docs = [{'text': 'Generic training manual. Record the gauge reading.', 'meta': {'source_file': 'AIR-01.pdf'}}]
    assert missing_requested_identifiers('AIR-01 應如何記錄？', docs) == ['AIR-01']
    assert missing_requested_identifiers('這份訓練手冊要求記錄什麼？', docs) == []


@pytest.mark.parametrize('text,filename,expected', [
    ('MOCK DATA - training only', 'manual.pdf', True),
    ('mock exercise', 'manual.pdf', True),
    ('這是模擬資料', 'manual.pdf', True),
    ('Manufacturer instructions', 'MOCK.pdf', False),
    ('Training instructions', 'manual.pdf', False),
    ('mockingbird', 'manual.pdf', False),
])
def test_mock_notice_uses_source_text_not_filename(text, filename, expected):
    assert bool(mock_evidence_notice([{'text': text, 'meta': {'source_file': filename}}])) is expected


@pytest.mark.parametrize('streaming,buffered', [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize('fails', [False, True])
def test_mock_notice_and_answer_snapshot_match_for_all_generation_paths(monkeypatch, streaming, buffered, fails):
    monkeypatch.setattr(chat_lookup_routes, 'get_existing_engine', lambda _: SimpleNamespace(ready=True, tokenizer_version='v2'))
    monkeypatch.setattr(chat_lookup_routes, 'build_augmented_messages', lambda *_: ([], DOCS))
    monkeypatch.setattr(chat_lookup_routes, 'build_grounded_diagnostic_answer', lambda *_: '')
    monkeypatch.setattr(chat_lookup_routes, 'is_troubleshooting_query', lambda _: buffered)
    monkeypatch.setattr(chat_lookup_routes, 'collection_config', lambda _: SimpleNamespace(prompt_profile='maintenance_v1'))
    answer = '原文摘錄：Record the gauge reading.\n繁中說明：記錄儀表讀值。'

    async def generate(*_args, **_kwargs):
        if fails:
            raise RuntimeError('test model failure')
        chat_lookup_routes.request_llm_source.set('ollama')
        return answer

    async def generate_stream(*_args, **_kwargs):
        if fails:
            raise RuntimeError('test model failure')
        chat_lookup_routes.request_llm_source.set('ollama')
        yield answer[:8]
        yield answer[8:]

    monkeypatch.setattr(chat_lookup_routes, 'call_llm_with_retrieval_guard', generate)
    monkeypatch.setattr(chat_lookup_routes, 'stream_ollama', generate_stream)
    request = ChatRequest(messages=[Message(role='user', content='文件要求記錄什麼？')], stream=streaming)
    saved = AsyncMock(return_value=True)
    with (patch.object(chat_lookup_routes, 'save_rag_answer_async', saved),
          patch.object(chat_lookup_routes, 'record_query'), patch.object(chat_lookup_routes, 'record_chat_error'),
          patch.object(chat_lookup_routes.runtime_metrics, 'record_rag')):
        response = asyncio.run(chat_lookup_routes.handle_chat(request, 'compressor_demo', {'user_id': 'operator'}))
        if streaming:
            async def consume():
                return ''.join([chunk async for chunk in response.body_iterator])
            body = asyncio.run(consume())
            events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith('data: {')]
            content = ''.join(e['choices'][0]['delta'].get('content', '') for e in events)
        else:
            content = response['choices'][0]['message']['content']
    assert content.startswith(mock_evidence_notice(DOCS))
    assert content.count('本次檢索包含 MOCK') == 1
    assert saved.await_args.kwargs['answer'] == content
    assert saved.await_args.kwargs['answer_state'] == ('unavailable' if fails else 'complete')
    if not fails:
        assert content == mock_evidence_notice(DOCS) + answer
        assert saved.await_args.kwargs['provider'] == 'ollama'


@pytest.mark.parametrize('streaming', [False, True])
def test_missing_identifier_never_reaches_model_and_persists_same_answer(streaming, monkeypatch):
    monkeypatch.setattr(chat_lookup_routes, 'get_existing_engine', lambda _: SimpleNamespace(ready=True, tokenizer_version='v2'))
    monkeypatch.setattr(chat_lookup_routes, 'build_augmented_messages', lambda *_: ([], DOCS))
    request = ChatRequest(messages=[Message(role='user', content='AIR-01 的 E-99 原因？')], stream=streaming)
    saved = AsyncMock(return_value=True)
    with (
        patch.object(chat_lookup_routes, 'save_rag_answer_async', saved),
        patch.object(chat_lookup_routes, 'record_query'),
        patch.object(chat_lookup_routes, 'call_llm', AsyncMock(side_effect=AssertionError('LLM must not be called'))),
        patch.object(chat_lookup_routes.runtime_metrics, 'record_rag'),
    ):
        response = asyncio.run(chat_lookup_routes.handle_chat(request, 'compressor_demo', {'user_id': 'operator'}))
        if streaming:
            async def consume():
                return ''.join([chunk async for chunk in response.body_iterator])
            body = asyncio.run(consume())
            chunks = [json.loads(line[6:]) for line in body.splitlines() if line.startswith('data: {')]
            content = ''.join(chunk['choices'][0]['delta'].get('content', '') for chunk in chunks)
            response_id = chunks[0]['id']
            assert 'data: [DONE]' in body
        else:
            content = response['choices'][0]['message']['content']
            response_id = response['id']
    assert '本次檢索內容未提供 E-99' in content
    assert 'Record the gauge' not in content and 'E-42' not in content
    result = saved.await_args.kwargs
    assert result['answer'] == content and result['answer_id'] == response_id
    assert result['provider'] == 'evidence_guard' and result['model'] == '' and result['answer_state'] == 'complete'
