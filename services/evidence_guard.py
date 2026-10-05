"""Check explicit identifiers against retrieved evidence before generating instructions.

This is a necessary-evidence check, not semantic validation or a statement about
the whole knowledge base. Ordinary quantities are not identifiers.
"""
import re


_HYPHENATED_ID = re.compile(
    r'(?<![A-Za-z0-9_-])[A-Za-z]{1,16}-[A-Za-z0-9]*\d[A-Za-z0-9-]*(?![A-Za-z0-9_-]|\.[A-Za-z]{2,5}\b)')
_ALARM_CODE = re.compile(
    r'(?:警報(?:代碼)?|警报(?:代码)?|报警(?:代码)?|\balarm(?:\s+code)?|\bcode)\s*[:：#]?\s*(\d{3,6})(?!\d)',
    re.IGNORECASE,
)


def mock_evidence_notice(docs: list[dict]) -> str:
    """Surface source notices without trusting the model to repeat them.

    Filenames alone do not establish whether content is synthetic. The notice
    describes the retrieved set, including mixed official and training sources.
    """
    if any(re.search(r'\bMOCK\b|模擬資料', str(doc.get('text') or ''), re.I) for doc in docs):
        return '本次檢索包含 MOCK 訓練資料，非實際設備操作指引。\n\n'
    return ''


def missing_requested_identifiers(query: str, docs: list[dict]) -> list[str]:
    requested = list(_HYPHENATED_ID.findall(query)) + _ALARM_CODE.findall(query)
    if re.fullmatch(r'\s*\d{3,6}(?:[\s,，、/]+\d{3,6})*\s*[?？]?\s*', query):
        requested.extend(re.findall(r'\d{3,6}', query))
    # A filename is provenance, not evidence about an equipment ID or alarm.
    evidence = '\n'.join(str(doc.get('text') or '') + '\n' + str(doc.get('meta', {}).get('code') or '')
                         for doc in docs)
    missing = []
    seen = set()
    for identifier in requested:
        normalized = identifier.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        if not re.search(r'(?<![A-Za-z0-9_-])' + re.escape(identifier) + r'(?![A-Za-z0-9_-])',
                         evidence, re.IGNORECASE):
            missing.append(identifier)
    return missing


def missing_identifier_answer(identifiers: list[str]) -> str:
    names = '、'.join(identifiers[:8]) + ('等識別碼' if len(identifiers) > 8 else '')
    return (f'本次檢索內容未提供 {names} 的對應資料，無法根據這些段落確認所問資訊。'
            '請提供對應設備或代碼的核准文件，或補充查詢條件；不能以其他設備或代碼的步驟代替。')
