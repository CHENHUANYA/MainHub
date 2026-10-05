"""Prepare shareable MOCK question/source packs and evaluate real demo-deployment RAG.

Automated gates check provenance and lexical signals, not semantic correctness.
Every answer still requires review. Only explicitly marked demo deployments can
be configured/imported by this engineering tool; ordinary SOP users use the UI.
"""
from __future__ import annotations

import argparse
from contextlib import suppress
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_local_rag import cites_source_page


EXPRESSION_CONTRACTS = {
    'excerpt_zh': '先逐字摘錄相關原句，再以繁中說明動作與對象，列出來源頁碼及 MOCK 非操作聲明。',
    'verbatim': '完整保留原文章節、順序與 MOCK 限制，列出來源頁碼；不要求翻譯。',
    'insufficient_zh': '用繁中說明本次檢索缺口，索取對應的具體核准文件，不借用其他設備處置或猜數值。',
}


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def expression_checks(case: dict, content: str, suite: dict) -> dict[str, bool]:
    """Check declared presentation requirements, never infer semantic correctness.

    Remove filenames before checking notices: a citation is not a MOCK warning.
    Case-specific Chinese terms check the explanation, not the English quote or
    Chinese headings. Human review must still validate each action and object.
    """
    prose = content
    for document in suite['documents']:
        prose = re.sub(re.escape(document['filename']), '', prose, flags=re.I)
    checks = {}
    if case['kind'] == 'supported':
        checks['mock_label_present'] = bool(re.search(r'\bMOCK\b|模擬|訓練', prose, re.I))
    contract = case.get('answer_contract')
    if not contract:
        return checks
    if contract not in EXPRESSION_CONTRACTS:
        raise ValueError(f'Unknown answer contract: {contract}')
    if contract in ('excerpt_zh', 'verbatim'):
        checks['mock_non_operational_notice'] = bool(re.search(
            r'非實際設備操作指引|不是.*(?:操作|維修)指引|not an (?:operating SOP|official manufacturer manual)'
            r'|not operational instructions|No real equipment operation is authorized', prose, re.I))
        normalized = ' '.join(content.split())
        if contract == 'verbatim':
            source = next(d for d in suite['documents'] if d['filename'] == case['source_file'])
            checks['complete_verbatim_excerpt'] = ' '.join(source['pages'][case['page'] - 1].split()) in normalized
        else:
            # Headings alone are insufficient: require the actual source sentences
            # and translated facts in their respective sections, in that order.
            excerpt, marker, explanation = content.partition('繁中說明：')
            quoted = excerpt.partition('原文摘錄：')[2]
            explanation = re.split(r'(?:來源|Source)\s*[:：]', explanation, maxsplit=1, flags=re.I)[0]
            checks['relevant_verbatim_excerpt'] = bool(quoted and marker and case.get('required_quotes')) and all(
                ' '.join(sentence.split()) in ' '.join(quoted.split()) for sentence in case.get('required_quotes', []))
            checks['chinese_explanation'] = bool(marker and case.get('zh_facts_any')) and all(
                any(term in explanation for term in group) for group in case.get('zh_facts_any', []))
    else:
        checks['scoped_missing_evidence'] = bool(re.search(r'本次(?:檢索|提供|取得)(?:的)?(?:內容|資料|片段)?', prose))
        requests = re.findall(r'請(?:提供|補充|補上|取得)([^。！？\n]*)', prose)
        checks['requests_specific_document'] = any(bool(re.search(r'文件|手冊|規格|資料表', document)) and all(
                any(term in document for term in group) for group in case.get('missing_document_terms', [])) and not bool(
                    re.search(r'具體核准文件名稱|實際文件名稱|\[.*?(?:document|filename).*?\]', document, re.I))
                for document in requests)
    return checks


def prepare(scenario: str, output: Path) -> dict:
    import fitz
    suite = json.loads((ROOT / 'templates' / f'acceptance.{scenario}-demo.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=False)
    for document in suite['documents']:
        with fitz.open() as pdf:
            for text in document['pages']:
                page = pdf.new_page()
                assert page.insert_textbox(fitz.Rect(45, 45, 550, 790), text, fontsize=12) >= 0
            target = output / document['filename']
            pdf.save(target)
        document['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    write_json(output / 'suite.json', suite)
    lines = ['# MOCK 查詢驗收問題卡', '', suite['scope'], '',
             '僅供隔離示範部署。先匯入同目錄 PDF，再逐題查詢，保留回答、引用與頁碼。', '',
             '自動檢查不能取代逐句比對；不得把模擬資料當成真實設備處置。', '']
    for case in suite['cases']:
        lines += [f"## {case['id']}", '', case['question'], '', f"預期：{case['expected']}", '',
                  '回答要求：' + EXPRESSION_CONTRACTS[case['answer_contract']], '',
                  f"正確來源：{case.get('source_file', '沒有足夠來源，應說明缺口')}；頁碼：{case.get('page', '不適用')}", '',
                  '實際回答／引用：＿＿＿　審閱結果：＿＿＿　審閱人：＿＿＿', '']
    (output / 'questions.md').write_text('\n'.join(lines), encoding='utf-8')
    return suite


def evaluate(case: dict, query: dict, record: dict, suite: dict) -> dict[str, bool]:
    answer = record.get('answer', {})
    content = str(answer.get('answer') or '')
    citations = query.get('rag', {}).get('citations', [])
    sources = {item['filename']: item for item in suite['documents']}
    checks = {
        'expected_answer_origin': (
            answer.get('provider') == 'ollama' and answer.get('model') == 'gemma4:e2b'
        ) or (case['kind'] == 'insufficient' and answer.get('provider') == 'evidence_guard' and answer.get('model') == ''),
        'complete_answer': answer.get('answer_state') == 'complete' and bool(content.strip()),
        'persisted_snapshot': answer.get('answer_id') == query.get('id') and content ==
            query.get('choices', [{}])[0].get('message', {}).get('content'),
        'own_collection': answer.get('collection') == suite['collection'] and
            query.get('rag', {}).get('collection') == suite['collection'],
        'citations_trace_to_imported_documents': all(
            c.get('source_file') in sources and c.get('source_hash') == sources[c['source_file']]['sha256']
            and isinstance(c.get('page'), int) and 1 <= c['page'] <= len(sources[c['source_file']]['pages'])
            and bool(c.get('section_id')) and bool(c.get('locator')) for c in citations),
    }
    if case['kind'] == 'supported':
        checks.update({
            'expected_source_page_retrieved': any(c.get('source_file') == case['source_file'] and
                c.get('page') == case['page'] for c in citations),
            'expected_source_page_in_answer': cites_source_page(content, case['source_file'], case['page']),
            'expected_facts_mentioned': all(any(term.casefold() in content.casefold() for term in group)
                                             for group in case['facts_any']),
        })
    else:
        checks['insufficiency_signal'] = any(term in content.casefold() for term in (
            '沒有', '未提供', '未包含', '未找到', '找不到', '無法', '不足', '未涵蓋', '不包含', '缺少', '未提及',
            '未指定', '不指定', 'not found', 'not provided', 'does not', 'no information', 'insufficient', 'specifies no'))
        checks['no_unsupported_numeric_setting'] = not any(re.search(pattern, content, re.I)
            for pattern in case.get('forbidden_patterns', []))
    checks.update(expression_checks(case, content, suite))
    return checks


def run(directory: Path, suite_path: Path, output: Path) -> dict:
    import httpx
    from dotenv import dotenv_values
    from scripts.verify_company_deployment import deployment_context
    from scripts.company_runtime_backup import Deployment

    deployment, company, base = deployment_context(directory)
    suite = json.loads(suite_path.read_text(encoding='utf-8'))
    if (suite.get('schema_version') != 1 or not suite.get('cases') or not suite.get('documents')
            or len({case['id'] for case in suite['cases']}) != len(suite['cases'])
            or any(case['kind'] not in ('supported', 'insufficient') for case in suite['cases'])):
        raise ValueError('A nonempty suite with unique cases and supported kinds is required')
    if any(case.get('answer_contract') not in EXPRESSION_CONTRACTS for case in suite['cases']):
        raise ValueError('Prepare a new suite with explicit answer contracts; retain old suites as historical evidence')
    if suite['company_id'] != company['company']['id'] or suite['collection'] != company['default_collection']:
        raise ValueError('Question suite and demo company must match')
    sources = {}
    for doc in suite['documents']:
        path = (suite_path.parent / doc['filename']).resolve()
        if path.parent != suite_path.parent.resolve() or hashlib.sha256(path.read_bytes()).hexdigest() != doc['sha256']:
            raise ValueError('Source file is outside suite directory or hash changed')
        sources[doc['filename']] = path
    Deployment(directory).wait_ready()
    output.mkdir(parents=True, exist_ok=False)
    credentials_path = directory / '.quality-credentials.json'
    if credentials_path.exists():
        credentials = json.loads(credentials_path.read_text(encoding='utf-8'))
    else:
        credentials = {'username': 'admin01', 'password': secrets.token_urlsafe(24)}
        write_json(credentials_path, credentials)
    report = {'status': 'ERROR', 'timestamp': datetime.now(timezone.utc).isoformat(), 'scenario': suite['scenario'],
              'project': deployment['project'], 'scope': suite['scope'], 'cases': [], 'controls': {},
              'evaluation_version': 'expression-contract-v2',
              'suite_sha256': hashlib.sha256(suite_path.read_bytes()).hexdigest(),
              'semantic_review': 'REQUIRED: lexical/provenance gates are not a semantic quality score'}
    collection = suite['collection']
    with httpx.Client(base_url=base, trust_env=False, timeout=300) as client:
        try:
            login = client.post('/auth/login', json=credentials)
            if login.status_code != 200:
                initial = dotenv_values(directory / '.env')['ADMIN_INITIAL_PASSWORD']
                changed = client.post('/auth/initial-password', json={'username': 'admin01',
                    'current_password': initial, 'new_password': credentials['password']})
                changed.raise_for_status()
                login = client.post('/auth/login', json=credentials)
            login.raise_for_status()
            config_preview = client.post('/company-config/preview', json={'config': company}).json()
            configured = client.put('/company-config', json={'config': company,
                'expected_revision': config_preview['expected_revision']})
            configured.raise_for_status()
            existing = client.get(f'/v1/{collection}/documents').json()['documents']
            if any(doc.get('source_hash') not in {d['sha256'] for d in suite['documents']} for doc in existing):
                raise ValueError('Demo has unrelated documents; use a fresh deployment, do not clear data')

            def query(question):
                response = client.post(f'/v1/{collection}/chat/completions', json={
                    'messages': [{'role': 'user', 'content': question}], 'stream': False,
                    'temperature': 0, 'max_tokens': 512})
                response.raise_for_status()
                payload = response.json()
                record = client.get('/rag/answers/' + payload['id'])
                record.raise_for_status()
                return payload, record.json()

            if not existing:
                empty_query, empty_record = query(suite['cases'][0]['question'])
                report['controls']['empty_collection_unavailable'] = (
                    empty_record['answer']['answer_state'] == 'unavailable' and not empty_query['rag']['citations'])
                write_json(output / 'empty-collection.json', {'query': empty_query, 'record': empty_record})
            foreign = 'compressor_demo' if collection == 'cnc_manual' else 'cnc_manual'
            rejected = client.post(f'/v1/{foreign}/chat/completions', json={
                'messages': [{'role': 'user', 'content': 'MOCK isolated company test'}]})
            report['controls']['other_collection_rejected'] = rejected.status_code in (400, 403, 404)
            for name, path in sources.items():
                imported = client.post(f'/v1/{collection}/ingest', files={'file': (name, path.read_bytes(), 'application/pdf')})
                assert imported.status_code in (200, 409), imported.status_code
                assert imported.json().get('status') in ('ok', 'duplicate')
            for case in suite['cases']:
                started = time.monotonic()
                payload, record = query(case['question'])
                checks = evaluate(case, payload, record, suite)
                result = {'id': case['id'], 'question': case['question'], 'expected': case['expected'],
                    'checks': checks, 'gate_status': 'PASS' if all(checks.values()) else 'FAIL',
                    'elapsed_seconds': round(time.monotonic() - started, 2), 'query': payload, 'record': record}
                report['cases'].append(result)
                write_json(output / 'report.json', report)
                print(f"{result['gate_status']}: {case['id']} ({result['elapsed_seconds']} s)", flush=True)
            health = client.get('/health/details').json()
            runtime = health['collections'][collection]['retrieval_runtime']
            report['retrieval_runtime'] = runtime
            report['controls']['embedding_loaded'] = runtime.get('embedding_loaded') is True
            # Chinese questions intentionally bypass the English reranker. Test
            # its execution separately; do not attribute that probe to answers.
            probe = client.get(f'/v1/{collection}/retrieve', params={
                'query': 'training worksheet observation timestamp maintenance team', 'top_k': 2})
            probe.raise_for_status()
            after_probe = client.get('/health/details').json()['collections'][collection]['retrieval_runtime']
            report['english_reranker_probe'] = {'retrieval': probe.json(), 'runtime': after_probe}
            report['controls']['english_probe_reranker_used'] = (after_probe.get('reranker_loaded') is True and
                after_probe.get('reranker_calls', 0) > runtime.get('reranker_calls', 0) and
                after_probe.get('last_retrieval_mode') == 'reranker' and not after_probe.get('last_reranker_error'))
            report['status'] = 'GATES_PASS_REVIEW_REQUIRED' if all(report['controls'].values()) and all(
                c['gate_status'] == 'PASS' for c in report['cases']) else 'GATES_FAIL'
        except Exception as exc:
            # No response bodies or credentials in failure logs.
            report['error'] = type(exc).__name__ + ': acceptance could not finish; inspect service health and inputs'
            raise
        finally:
            write_json(output / 'report.json', report)
            lines = ['# MOCK 回答審閱紀錄', '', report['status'], '', report['semantic_review'], '']
            for case in report['cases']:
                lines += [f"## {case['id']}", '', case['question'], '', f"預期：{case['expected']}", '',
                    '實際回答：', '', case['record']['answer']['answer'], '',
                    '未通過檢查：' + ', '.join(k for k, v in case['checks'].items() if not v), '',
                    '逐句支持／正確引用／資料缺口／額外推測：待審閱', '']
            (output / 'review.md').write_text('\n'.join(lines), encoding='utf-8')
            with suppress(httpx.HTTPError):
                client.post('/auth/logout')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    create = commands.add_parser('prepare')
    create.add_argument('--scenario', choices=['cnc', 'compressor', 'grounding'], required=True)
    create.add_argument('--output', type=Path, required=True)
    execute = commands.add_parser('run')
    execute.add_argument('--deployment', type=Path, required=True)
    execute.add_argument('--suite', type=Path, required=True)
    execute.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.scenario, args.output)
    else:
        result = run(args.deployment.resolve(), args.suite.resolve(), args.output)
        raise SystemExit(0 if result['status'] == 'GATES_PASS_REVIEW_REQUIRED' else 1)
