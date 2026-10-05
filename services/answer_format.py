"""Mechanical maintenance-answer checks; these do not certify semantic correctness."""
from __future__ import annotations

import re

from services.prompt_profiles import MAINTENANCE_SYSTEM


def requires_answer_check(messages: list[dict]) -> bool:
    return bool(messages and messages[0].get('role') == 'system'
                and messages[0].get('content') == MAINTENANCE_SYSTEM)


def cites_source_page(content: str, source: str, page: int) -> bool:
    """Check a literal filename/page pair separately from retrieval metadata."""
    filename = r'(?<![\w./-])' + re.escape(source) + r'(?![\w./-])'
    locator = rf'(?:第\s*{page}\s*頁|\b(?:pages?|p\.)\s*{page}(?!\d))'
    separator = r'[\s\[\]()（）,，:：;；|*_-]{0,40}'
    return bool(re.search(
        rf'{filename}{separator}{locator}|{locator}{separator}(?:(?:source|來源){separator})?{filename}',
        content, re.IGNORECASE))


def requested_document(query: str) -> str:
    """Name evidence to request, never supply a setting or operating procedure."""
    documents = []
    if re.search(r'壓力|压力|pressure|\b(?:bar|psi|mpa)\b', query, re.I):
        documents.append('對應設備的核准壓力規格')
    if re.search(r'扭矩|扭力|torque|\bnm\b|N[·⋅]m', query, re.I):
        documents.append('對應型號的核准扭矩規格')
    if re.search(r'警報|警报|报警|代碼|代码|\balarm\b|\bcode\b', query, re.I):
        documents.append('所問設備與代碼對應的核准警報手冊')
    return '及'.join(documents) if documents else '所問設備的適用型號資料及涵蓋該問題的核准手冊'


def _insufficient(content: str) -> bool:
    # Restrict classification to prose outside quoted evidence. A supported
    # answer may quote a source saying "no pressure limit" for a different topic.
    prose = re.split(r'原文摘錄\s*[:：]', content, maxsplit=1)[0]
    return bool(re.search(r'本次(?:檢索|提供|取得).*?(?:未提供|未涵蓋|未包含|未找到|缺少|不足|無法確認)',
                          prose, re.S))


def complete_document_request(content: str, query: str) -> str:
    if not _insufficient(content):
        return content
    document = requested_document(query)
    # Require the requested document in the request clause, not merely a term
    # mentioned earlier in the missing-evidence sentence. No model retry needed.
    requests = list(re.finditer(r'請(?:提供|補充|補上|取得)([^。！？\n]*)', content))
    topics = [word for word in ('壓力', '扭矩', '警報') if word in document]
    if any(re.search(r'文件|手冊|規格|資料表', request.group(1))
           and all(topic in request.group(1) for topic in topics)
           and not re.search(r'具體.*名稱|\[|【', request.group(1)) for request in requests):
        return content
    if requests:
        first = requests[0]
        return content[:first.start()] + f'請提供{document}' + content[first.end():]
    return content.rstrip() + f'\n\n需要補件：請提供{document}。'


def _normalize(text: str) -> str:
    return ' '.join(text.split())


def maintenance_format_issues(content: str, docs: list[dict]) -> list[str]:
    """Verify the quote/explanation/citation contract, not truth of the explanation."""
    if _insufficient(content):
        # A refusal must not smuggle other equipment instructions in an excerpt.
        return ['資料不足時不要附其他設備摘錄'] if '原文摘錄' in content else []
    match = re.search(r'原文摘錄\s*[:：](.*?)繁中說明\s*[:：](.*)', content, re.S)
    if not match:
        return ['依序提供原文摘錄、繁中說明與來源，不能省略任何一段']
    quote, explanation = match.groups()
    quote = re.split(r'(?:來源|Source)\s*[:：]', quote, maxsplit=1, flags=re.I)[0]
    explanation = re.split(r'(?:來源|Source)\s*[:：]', explanation, maxsplit=1, flags=re.I)[0]
    # Accept Markdown blockquotes and wrapping quotation marks without changing
    # the original wording. Multiple quoted lines may come from different pages.
    lines = [line.strip().removeprefix('>').strip().strip('"“”「」') for line in quote.splitlines()]
    lines = [line for line in lines if line and line not in ('```', '**')]
    issues = []
    if not lines:
        issues.append('摘錄不能空白')
    for line in lines:
        matches = [doc for doc in docs if _normalize(line) in _normalize(str(doc.get('text') or ''))]
        if not matches:
            issues.append('摘錄必須逐字來自提供的原文，不得改寫或杜撰')
            break
        if not any(_has_citation(content, doc) for doc in matches):
            issues.append('每段摘錄須列出其實際檔名及頁碼')
            break
    if not re.search(r'[\u3400-\u9fff]', explanation):
        issues.append('繁中說明必須有實際中文內容，不能只保留標題或英文')
    return issues


def _has_citation(content: str, doc: dict) -> bool:
    meta = doc.get('meta') or {}
    source = str(meta.get('source_file') or meta.get('source') or '')
    page = meta.get('page')
    return bool(source and isinstance(page, int) and not isinstance(page, bool)
                and cites_source_page(content, source, page))


def repair_messages(messages: list[dict], issues: list[str]) -> list[dict]:
    repaired = [dict(message) for message in messages]
    repaired[0]['content'] += ('\n\n回答格式核對未通過：' + '；'.join(issues) +
        '。請重新依原始問題與原文作答，不新增事實。資料足夠時嚴格依序輸出：\n'
        '原文摘錄：\n（直接複製相關原句）\n繁中說明：\n（翻譯動作與對象）\n來源：實際檔名，第 N 頁。')
    return repaired


INCOMPLETE_ANSWER = ('模型回答未通過原文摘錄、繁中說明或來源格式檢查，本次未提供完整回答。'
                     '請依引用核對原文，或稍後重新查詢。')
