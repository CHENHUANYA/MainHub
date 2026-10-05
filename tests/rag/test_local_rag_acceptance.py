from copy import deepcopy

import pytest

from scripts.verify_local_rag import cites_source_page, evaluate_evidence


def evidence():
    content = "Record gauge reading [MOCK.pdf, Page 1]"
    query = {"id": "answer-1", "choices": [{"message": {"content": content}}],
             "rag": {"collection": "demo", "citations": [{"source_file": "MOCK.pdf", "page": 1,
                     "source_hash": "a" * 64, "section_id": "section-1", "locator": "p.1"}]}}
    record = {"answer": {"answer_id": "answer-1", "collection": "demo", "answer": content,
                         "provider": "ollama", "model": "gemma4:e2b", "answer_state": "complete"}}
    health = {"collections": {"demo": {"retrieval_runtime": {
        "embedding_loaded": True, "reranker_loaded": True, "reranker_active": True,
        "reranker_calls": 1, "last_reranker_error": "",
    }}}}
    return query, record, health


def check(query, record, health):
    return evaluate_evidence(query, record, health, collection="demo", model="gemma4:e2b", source="MOCK.pdf",
                             page=1, source_hash="a" * 64, required_terms=["gauge"])


def test_acceptance_requires_real_provider_answer_source_and_loaded_models():
    assert all(check(*evidence()).values())


def test_mixed_corpus_can_cite_pdf_after_approved_knowledge_but_still_requires_hash():
    query, record, health = evidence()
    query['rag']['citations'].insert(0, {'source_file': 'workorder', 'page': 0})
    def mixed_check():
        return evaluate_evidence(query, record, health, collection='demo', model='gemma4:e2b',
            source='MOCK.pdf', page=1, source_hash='a' * 64, required_terms=['gauge'], require_first_citation=False)
    assert not all(check(query, record, health).values())
    assert all(mixed_check().values())
    query['rag']['citations'][1]['source_hash'] = 'wrong'
    assert not all(mixed_check().values())


@pytest.mark.parametrize('content', [
    'Record gauge reading [MOCK.pdf, Page 3]',
    'Record gauge reading [OTHER.pdf, Page 1]',
    'Record gauge reading',
    'MOCK DATA 訓練出席 (MOCK.pdf, Page 3)',
])
def test_correct_retrieval_metadata_cannot_hide_missing_or_wrong_answer_citation(content):
    query, record, health = evidence()
    query['choices'][0]['message']['content'] = record['answer']['answer'] = content
    result = check(query, record, health)
    assert result['answer_snapshot_matches'] and result['expected_document_page_hash']
    assert not result['expected_source_page_in_answer']


@pytest.mark.parametrize('content,expected', [
    ('來源：MOCK.pdf，第 1 頁。', True),
    ('[MOCK.pdf, P.1]', True),
    ('[Page 1 | Source: MOCK.pdf]', True),
    ('MOCK.pdf, Page 10', False),
    ('OTHER-MOCK.pdf, Page 1', False),
    ('MOCK.pdf.bak, Page 1', False),
    ('MOCK.pdf, Page 3; OTHER.pdf, Page 1', False),
])
def test_answer_citation_pairs_filename_with_exact_page(content, expected):
    assert cites_source_page(content, 'MOCK.pdf', 1) is expected


@pytest.mark.parametrize("failure", ["fallback", "empty", "wrong_hash", "wrong_page", "unloaded", "reranker_error",
                                    "not_top_source", "wrong_snapshot"])
def test_acceptance_cannot_pass_on_fallback_or_incorrect_evidence(failure):
    query, record, health = evidence()
    answer = record["answer"]
    runtime = health["collections"]["demo"]["retrieval_runtime"]
    if failure == "fallback":
        answer.update(provider="retrieval", model="", answer_state="fallback")
    elif failure == "empty":
        answer["answer"] = ""
    elif failure == "wrong_hash":
        query["rag"]["citations"][0]["source_hash"] = "b" * 64
    elif failure == "wrong_page":
        query["rag"]["citations"][0]["page"] = 2
    elif failure == "unloaded":
        runtime["embedding_loaded"] = False
    elif failure == "reranker_error":
        runtime["last_reranker_error"] = "failed"
    elif failure == "not_top_source":
        wrong = deepcopy(query["rag"]["citations"][0])
        wrong["page"] = 2
        query["rag"]["citations"].insert(0, wrong)
    else:
        answer["answer_id"] = "different-answer"
    assert not all(check(query, record, health).values())
