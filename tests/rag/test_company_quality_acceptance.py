from copy import deepcopy
import hashlib

import fitz
import pytest

from scripts.verify_company_rag_quality import evaluate, expression_checks, prepare


@pytest.mark.parametrize('scenario', ['cnc', 'compressor', 'grounding'])
def test_demo_pack_has_exact_readable_source_pages_and_refuses_overwrite(tmp_path, scenario):
    target = tmp_path / scenario
    suite = prepare(scenario, target)
    assert len(suite['cases']) == 5
    for source in suite['documents']:
        path = target / source['filename']
        assert source['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
        with fitz.open(path) as pdf:
            assert len(pdf) == len(source['pages'])
            for page, expected in zip(pdf, source['pages']):
                assert ' '.join(page.get_text().split()) == ' '.join(expected.split())
    with pytest.raises(FileExistsError):
        prepare(scenario, target)


def evidence():
    suite = {'collection': 'demo', 'documents': [{'filename': 'MOCK.pdf', 'sha256': 'abc', 'pages': ['text']}]}
    answer = 'MOCK VIOLET observation timestamp [MOCK.pdf, Page 1]'
    case = {'kind': 'supported', 'source_file': 'MOCK.pdf', 'page': 1, 'facts_any': [['VIOLET'], ['timestamp']]}
    query = {'id': 'a', 'choices': [{'message': {'content': answer}}],
             'rag': {'collection': 'demo', 'citations': [{'source_file': 'MOCK.pdf', 'page': 1,
               'source_hash': 'abc', 'section_id': 's', 'locator': 'p.1'}]}}
    record = {'answer': {'provider': 'ollama', 'model': 'gemma4:e2b', 'answer_state': 'complete',
                        'answer_id': 'a', 'collection': 'demo', 'answer': answer}}
    return case, query, record, suite


def test_provenance_and_expected_facts_are_separate_checks():
    assert all(evaluate(*evidence()).values())


@pytest.mark.parametrize('failure', ['provider', 'snapshot', 'page', 'hash', 'company', 'no_citation', 'mock', 'fact', 'answer_page'])
def test_gate_rejects_fallback_wrong_sources_and_missing_expected_content(failure):
    case, query, record, suite = deepcopy(evidence())
    if failure == 'provider':
        record['answer']['provider'] = 'retrieval'
    elif failure == 'snapshot':
        record['answer']['answer_id'] = 'different'
    elif failure in ('page', 'hash'):
        query['rag']['citations'][0]['page' if failure == 'page' else 'source_hash'] = 9 if failure == 'page' else 'wrong'
    elif failure == 'company':
        query['rag']['collection'] = 'foreign'
    elif failure == 'no_citation':
        query['rag']['citations'] = []
    elif failure == 'answer_page':
        content = record['answer']['answer'].replace('Page 1', 'Page 3')
        record['answer']['answer'] = query['choices'][0]['message']['content'] = content
    else:
        content = record['answer']['answer'].replace('MOCK' if failure == 'mock' else 'VIOLET', '')
        record['answer']['answer'] = query['choices'][0]['message']['content'] = content
    assert not all(evaluate(case, query, record, suite).values())


def test_insufficient_signal_cannot_hide_an_invented_numeric_setting():
    _, query, record, suite = evidence()
    case = {'kind': 'insufficient', 'forbidden_patterns': [r'\d+\s*bar']}
    content = '資料不足，但可以設定 8 bar。'
    record['answer']['answer'] = query['choices'][0]['message']['content'] = content
    checks = evaluate(case, query, record, suite)
    assert checks['insufficiency_signal']
    assert not checks['no_unsupported_numeric_setting']


def test_short_missing_evidence_answer_is_recognized():
    _, query, record, suite = evidence()
    content = '缺少關於 AIR-01 安全壓力上限的資訊。'
    record['answer']['answer'] = query['choices'][0]['message']['content'] = content
    assert all(evaluate({'kind': 'insufficient'}, query, record, suite).values())


def test_guard_refusal_is_explicitly_separate_from_real_model_answers():
    _, query, record, suite = evidence()
    content = '本次檢索內容未提供 E-99 的對應資料。'
    record['answer']['answer'] = query['choices'][0]['message']['content'] = content
    record['answer'].update(provider='evidence_guard', model='')
    assert all(evaluate({'kind': 'insufficient'}, query, record, suite).values())
    record['answer']['provider'] = 'retrieval'
    assert not evaluate({'kind': 'insufficient'}, query, record, suite)['expected_answer_origin']
    record['answer'].update(provider='evidence_guard', model='gemma4:e2b')
    assert not evaluate({'kind': 'insufficient'}, query, record, suite)['expected_answer_origin']


def test_explicit_unspecified_parameter_is_insufficient_but_invented_value_still_fails():
    _, query, record, suite = evidence()
    case = {'kind': 'insufficient', 'forbidden_patterns': [r'\d+\s*bar']}
    for content in ('此文件不指定壓力限制。', 'This document specifies no pressure limit.'):
        record['answer']['answer'] = query['choices'][0]['message']['content'] = content
        assert all(evaluate(case, query, record, suite).values())
    record['answer']['answer'] = query['choices'][0]['message']['content'] = '此文件不指定壓力限制，但請設定 8 bar。'
    assert not all(evaluate(case, query, record, suite).values())


def test_cnc_parser_retains_actual_field_boundaries(tmp_path):
    from ingest import extract_alarm_sections
    suite = prepare('cnc', tmp_path / 'pack')
    sections = extract_alarm_sections(str(tmp_path / 'pack' / suite['documents'][0]['filename']))
    assert len(sections) == 2
    for section in sections:
        assert '\nExplanation:\n' in section['text'] and '\nRemedy:\n' in section['text']
        assert section['text'].index('Explanation:') < section['text'].index('Remedy:')
        assert 'Reaction:' not in section['text']


def test_filename_is_not_a_mock_notice():
    case, query, record, suite = evidence()
    content = 'VIOLET observation timestamp [MOCK.pdf, Page 1]'
    record['answer']['answer'] = query['choices'][0]['message']['content'] = content
    assert not evaluate(case, query, record, suite)['mock_label_present']


def expression_case():
    case = {'kind': 'supported', 'answer_contract': 'excerpt_zh',
            'required_quotes': ['Record the gauge reading.', 'Report to maintenance.'],
            'zh_facts_any': [['記錄'], ['儀表'], ['通報'], ['維修']]}
    suite = {'documents': [{'filename': 'MOCK.pdf'}]}
    content = ('MOCK 訓練資料，非實際設備操作指引。\n原文摘錄：\n'
               'Record the gauge reading.\nReport to maintenance.\n'
               '繁中說明：\n記錄儀表讀值並通報維修。\n來源：MOCK.pdf，第 1 頁。')
    return case, content, suite


def test_maintenance_requires_quote_translation_and_separate_notice():
    assert all(expression_checks(*expression_case()).values())


@pytest.mark.parametrize('change,failed', [
    ('english_only', 'chinese_explanation'),
    ('heading_only', 'chinese_explanation'),
    ('no_quote', 'relevant_verbatim_excerpt'),
    ('wrong_action', 'chinese_explanation'),
    ('paraphrase', 'relevant_verbatim_excerpt'),
    ('reversed', 'relevant_verbatim_excerpt'),
    ('no_notice', 'mock_non_operational_notice'),
])
def test_expression_regressions_cannot_pass_on_citation_or_headings(change, failed):
    case, content, suite = expression_case()
    translation = '記錄儀表讀值並通報維修。'
    if change == 'english_only':
        content = content.replace(translation, 'Record the gauge reading. Report to maintenance.')
    elif change == 'heading_only':
        content = content.replace(translation, '')
    elif change == 'wrong_action':
        content = content.replace(translation, '維修人員看儀表。')
    elif change == 'no_quote':
        content = content.replace('Record the gauge reading.\nReport to maintenance.', '')
    elif change == 'paraphrase':
        content = content.replace('Record the gauge reading.', 'Check the gauge.')
    elif change == 'reversed':
        content = '繁中說明：' + translation + '\n' + content.replace('繁中說明：', '')
    elif change == 'no_notice':
        content = content.replace('MOCK 訓練資料，非實際設備操作指引。', '')
    assert not expression_checks(case, content, suite)[failed]


def test_cnc_verbatim_english_is_valid_but_missing_source_sentence_is_not():
    source = ('3101\nExplanation:\nMOCK DATA ONLY. This is not an official manufacturer manual.\n'
              'Remedy:\nRecord BLUE.\nNo real equipment operation is authorized by this exercise.')
    suite = {'documents': [{'filename': 'MOCK.pdf', 'pages': [source]}]}
    case = {'kind': 'supported', 'answer_contract': 'verbatim', 'source_file': 'MOCK.pdf', 'page': 1}
    content = '原文摘錄：\n' + source + '\n來源：MOCK.pdf，第 1 頁。'
    assert all(expression_checks(case, content, suite).values())
    assert not expression_checks(case, content.replace('Record BLUE.', ''), suite)['complete_verbatim_excerpt']


@pytest.mark.parametrize('content,passed', [
    ('缺少安全壓力上限。', False),
    ('本次檢索內容未提供安全壓力上限。', False),
    ('本次檢索內容未提供安全壓力上限，請提供設備壓力規格。', True),
    ('知識庫沒有安全壓力上限，請提供設備壓力規格。', False),
    ('本次檢索內容未提供資訊，請提供設備規格。', False),
    ('本次檢索內容未提供壓力上限，請提供對應設備的核准文件。', False),
    ('本次檢索內容未提供壓力上限，請提供【壓力的具體核准文件名稱】。', False),
])
def test_insufficient_answer_names_scoped_gap_and_needed_document(content, passed):
    case = {'kind': 'insufficient', 'answer_contract': 'insufficient_zh', 'missing_document_terms': [['壓力']]}
    assert all(expression_checks(case, content, {'documents': []}).values()) is passed


def test_unknown_expression_contract_fails_instead_of_silently_skipping():
    with pytest.raises(ValueError, match='Unknown answer contract'):
        expression_checks({'kind': 'insufficient', 'answer_contract': 'typo'}, '', {'documents': []})
