import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app_context import ChatRequest, Message
from routes import chat_lookup_routes as routes
from services.answer_format import (
    INCOMPLETE_ANSWER, complete_document_request, maintenance_format_issues,
    requested_document, requires_answer_check,
)
from services.evidence_guard import mock_evidence_notice
from services.prompt_profiles import MAINTENANCE_SYSTEM, SYSTEM_PROMPT

DOCS = [{'text': 'MOCK DATA\nAIR-01 / E-43\nWhen the training card reads E-43, send worksheet Q-17 to the maintenance team.',
         'meta': {'source_file': 'MOCK-compressor-SOP.pdf', 'page': 2}}]
VALID = ('原文摘錄：\nWhen the training card reads E-43, send worksheet Q-17 to the maintenance team.\n'
         '繁中說明：\n當訓練卡顯示 E-43，將 Q-17 交給維修團隊。\n來源：MOCK-compressor-SOP.pdf，第 2 頁。')
MISSING_QUOTE = ('來源：MOCK-compressor-SOP.pdf，第 2 頁。\n'
                 '繁中說明：當訓練卡讀取 E-43 時，應將工作表 Q-17 寄給維護團隊。')
MESSAGES = [{'role': 'system', 'content': MAINTENANCE_SYSTEM}, {'role': 'user', 'content': 'original context'}]


def test_maintenance_contract_does_not_apply_to_cnc_verbatim():
    assert requires_answer_check(MESSAGES)
    assert not requires_answer_check([{'role': 'system', 'content': SYSTEM_PROMPT}])
    assert not requires_answer_check([{'role': 'user', 'content': MAINTENANCE_SYSTEM}])


@pytest.mark.parametrize('answer', [VALID, VALID.replace('When the', '> When the')])
def test_supported_quote_and_its_own_citation_pass(answer):
    assert maintenance_format_issues(answer, DOCS) == []


@pytest.mark.parametrize('answer', [
    MISSING_QUOTE,
    VALID.replace('第 2 頁', '第 1 頁'),
    VALID.replace('MOCK-compressor-SOP.pdf', 'other.pdf'),
    VALID.replace('send worksheet', 'destroy worksheet'),
    VALID.replace('當訓練卡顯示 E-43，將 Q-17 交給維修團隊。', 'Send Q-17 to maintenance.'),
    VALID.replace('When the training card reads E-43, send worksheet Q-17 to the maintenance team.', ''),
    '',
    '本次檢索內容未提供 AIR-01 對應處置。\n' + VALID,
])
def test_missing_or_untraceable_quote_cannot_pass(answer):
    assert maintenance_format_issues(answer, DOCS)


def test_source_saying_no_parameter_does_not_turn_supported_answer_into_refusal():
    docs = [{'text': 'No pressure limit is specified. Record the reading.', 'meta': {'source_file': 'manual.pdf', 'page': 1}}]
    answer = '原文摘錄：\nNo pressure limit is specified.\n繁中說明：此段沒有指定壓力上限。\n來源：manual.pdf，第 1 頁。'
    assert not maintenance_format_issues(answer, docs)
    assert complete_document_request(answer, 'What does this sentence say?') == answer


@pytest.mark.parametrize('question,expected', [
    ('AIR-01 安全壓力上限？', '核准壓力規格'),
    ('CNC-01 torque in Nm?', '核准扭矩規格'),
    ('警報 3999 原因？', '核准警報手冊'),
    ('AIR-01 的 E-42 應記錄什麼？', '適用型號資料'),
])
def test_incomplete_document_request_gets_specific_non_operational_evidence_request(question, expected):
    original = '本次檢索內容未提供所問資訊。請提供對應設備的核准資訊。'
    answer = complete_document_request(original, question)
    assert answer.startswith('本次檢索內容未提供所問資訊。')
    assert expected in answer
    assert '請提供' in answer and '核准資訊' not in answer


def test_document_request_is_idempotent_and_checks_request_clause():
    original = '本次檢索內容未提供扭矩，請提供核准文件。'
    answer = complete_document_request(original, 'torque?')
    assert answer != original
    assert complete_document_request(answer, 'torque?') == answer


def test_multiple_missing_topics_request_both_specs():
    assert '壓力規格' in requested_document('pressure and torque')
    assert '扭矩規格' in requested_document('pressure and torque')


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('results,expected,state,provider', [
    ([VALID], VALID, 'complete', 'ollama'),
    ([MISSING_QUOTE, VALID], VALID, 'complete', 'ollama'),
    ([MISSING_QUOTE, MISSING_QUOTE], INCOMPLETE_ANSWER, 'fallback', 'answer_guard'),
])
def test_same_bounded_guard_runs_before_json_or_sse_is_delivered(monkeypatch, streaming, results, expected, state, provider):
    monkeypatch.setattr(routes, 'get_existing_engine', lambda _: SimpleNamespace(ready=True, tokenizer_version='v2'))
    monkeypatch.setattr(routes, 'build_augmented_messages', lambda *_: (MESSAGES, DOCS))
    monkeypatch.setattr(routes, 'build_grounded_diagnostic_answer', lambda *_: '')
    request = ChatRequest(messages=[Message(role='user', content='AIR-01 的 E-43 要交哪份表單？')], stream=streaming)
    save = AsyncMock(return_value=True)
    model = AsyncMock(side_effect=results)
    with (patch.object(routes, 'call_ollama', model), patch.object(routes, 'save_rag_answer_async', save),
          patch.object(routes, 'stream_ollama', side_effect=AssertionError('Do not emit unchecked maintenance tokens')),
          patch.object(routes, 'record_query'), patch.object(routes.runtime_metrics, 'record_rag')):
        response = asyncio.run(routes.handle_chat(request, '808d', {'user_id': 'operator'}))
        if streaming:
            async def consume():
                return ''.join([event async for event in response.body_iterator])
            body = asyncio.run(consume())
            events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith('data: {')]
            content = ''.join(e['choices'][0]['delta'].get('content', '') for e in events)
            assert 'data: [DONE]' in body
        else:
            content = response['choices'][0]['message']['content']
    assert content == mock_evidence_notice(DOCS) + expected
    assert model.await_count == len(results)
    assert save.await_args.kwargs['answer'] == content
    assert save.await_args.kwargs['answer_state'] == state
    assert save.await_args.kwargs['provider'] == provider
    if provider == 'answer_guard':
        assert save.await_args.kwargs['model'] == ''
    assert MESSAGES[0]['content'] == MAINTENANCE_SYSTEM  # no in-place repair mutation


def test_refusal_supplements_document_without_extra_model_call():
    raw = '本次檢索內容未提供所問扭矩，請提供核准資訊。'
    with patch.object(routes, 'call_llm', AsyncMock(return_value=raw)) as call:
        answer = asyncio.run(routes.call_llm_with_retrieval_guard(MESSAGES, DOCS, '扭矩是多少？', 0, 512))
    call.assert_awaited_once()
    assert '核准扭矩規格' in answer


def test_cancelled_checked_stream_does_not_emit_or_persist_partial_answer(monkeypatch):
    monkeypatch.setattr(routes, 'get_existing_engine', lambda _: SimpleNamespace(ready=True, tokenizer_version='v2'))
    monkeypatch.setattr(routes, 'build_augmented_messages', lambda *_: (MESSAGES, DOCS))
    monkeypatch.setattr(routes, 'build_grounded_diagnostic_answer', lambda *_: '')
    request = ChatRequest(messages=[Message(role='user', content='AIR-01 / E-43')], stream=True)
    with (patch.object(routes, 'call_ollama', AsyncMock(side_effect=asyncio.CancelledError)),
          patch.object(routes, 'save_rag_answer_async', AsyncMock()) as save,
          patch.object(routes.runtime_metrics, 'record_rag') as metric):
        response = asyncio.run(routes.handle_chat(request, '808d', {'user_id': 'operator'}))
        async def consume():
            async for _event in response.body_iterator:
                pytest.fail('No unchecked content may be emitted')
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(consume())
    save.assert_not_awaited()
    assert metric.call_args.kwargs['outcome'] == 'interrupted'
