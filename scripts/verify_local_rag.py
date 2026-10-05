"""Check authenticated, real Ollama RAG against an already imported document.

Does not create accounts, change configuration, or import documents. The query
creates the application's normal answer/audit records. Credentials stay in env.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.answer_format import cites_source_page


def evaluate_evidence(query: dict, record: dict, health: dict, *, collection: str,
                      model: str, source: str, page: int, source_hash: str,
                      required_terms: list[str], require_first_citation: bool = True) -> dict[str, bool]:
    answer = record.get("answer", {})
    content = str(answer.get("answer") or "")
    citations = query.get("rag", {}).get("citations", [])
    runtime = health.get("collections", {}).get(collection, {}).get("retrieval_runtime", {})
    matching = [c for c in citations if c.get("source_file") == source and c.get("page") == page
                and c.get("source_hash") == source_hash and c.get("section_id") and c.get("locator")]
    response_text = next((c.get("message", {}).get("content", "") for c in query.get("choices", [])), "")
    return {
        "model_is_real_ollama": answer.get("provider") == "ollama" and answer.get("model") == model,
        "answer_complete": answer.get("answer_state") == "complete" and bool(content.strip()),
        "answer_snapshot_matches": answer.get("answer_id") == query.get("id") and content == response_text,
        "collection_matches": answer.get("collection") == collection and query.get("rag", {}).get("collection") == collection,
        "expected_document_page_hash": bool(matching) and (not require_first_citation or citations[0] in matching),
        "expected_source_page_in_answer": cites_source_page(content, source, page),
        "required_answer_terms": all(term.casefold() in content.casefold() for term in required_terms),
        "embedding_loaded": runtime.get("embedding_loaded") is True,
        "reranker_used": runtime.get("reranker_loaded") is True and runtime.get("reranker_active") is True
                         and int(runtime.get("reranker_calls") or 0) > 0 and not runtime.get("last_reranker_error"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8123")
    parser.add_argument("--username", default="admin01")
    parser.add_argument("--password-env", default="ACCEPTANCE_ADMIN_PASSWORD")
    parser.add_argument("--collection", required=True)
    parser.add_argument("--model", default="gemma4:e2b")
    parser.add_argument("--question", required=True)
    parser.add_argument("--source-file", type=Path, required=True, help="original PDF; basename and SHA256 must match citation")
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--required-answer-term", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True, help="new report file; refuses overwrites")
    args = parser.parse_args()
    password = os.getenv(args.password_env, "")
    if not password:
        parser.error(f"Set {args.password_env} to the account's current password")
    if args.output.exists():
        parser.error("Output already exists; choose a new report file")
    source_hash = hashlib.sha256(args.source_file.read_bytes()).hexdigest()
    report: dict = {
        "status": "FAIL", "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url, "collection": args.collection, "model": args.model,
        "source_file": args.source_file.name, "source_hash": source_hash, "expected_page": args.page,
        "question": args.question, "required_answer_terms": args.required_answer_term,
        "scope": "Authenticated HTTP; real container/model/retrieval. Not a browser or equipment safety acceptance.",
    }
    start = time.monotonic()
    try:
        with httpx.Client(base_url=args.base_url.rstrip('/'), timeout=240, trust_env=False) as client:
            login = client.post('/auth/login', json={"username": args.username, "password": password})
            login.raise_for_status()
            client.headers['Authorization'] = 'Bearer ' + login.json()['token']
            def get(path):
                response = client.get(path)
                response.raise_for_status()
                return response.json()
            response = client.post(f'/v1/{args.collection}/chat/completions', json={
                "messages": [{"role": "user", "content": args.question}], "max_tokens": 256, "stream": False,
            })
            response.raise_for_status()
            query = response.json()
            record = get('/rag/answers/' + query['id'])
            health = get('/health/details')
            checks = evaluate_evidence(query, record, health, collection=args.collection, model=args.model,
                                       source=args.source_file.name, page=args.page, source_hash=source_hash,
                                       required_terms=args.required_answer_term)
            report.update(checks=checks, query=query, answer_record=record,
                          retrieval_runtime=health.get('collections', {}).get(args.collection, {}).get('retrieval_runtime', {}))
            report['status'] = 'PASS' if all(checks.values()) else 'FAIL'
            client.post('/auth/logout')
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    report['elapsed_seconds'] = round(time.monotonic() - start, 2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(f"{report['status']}: {args.output}")
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
