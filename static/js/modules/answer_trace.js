(function initAnswerTrace(global) {
  const VALID_STATES = new Set(['complete', 'fallback', 'unavailable']);
  const STATE_LABELS = { complete: '回答已完成', fallback: '使用備援回答', unavailable: '無法取得回答' };
  let requestVersion = 0;

  function app() { return global.AlarmApp || null; }

  function ensureModal() {
    let modal = document.getElementById('answerTraceModal');
    if (modal) return modal;
    modal = document.createElement('dialog');
    modal.id = 'answerTraceModal';
    modal.className = 'answer-trace-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'answerTraceTitle');
    modal.innerHTML = `
      <div class="answer-trace-card">
        <div class="answer-trace-head">
          <div><h2 id="answerTraceTitle" class="answer-trace-title">RAG 回答快照</h2><p class="answer-trace-subtitle">查看當時的問題、回答與引用來源</p></div>
          <button class="wo-btn alt" type="button" data-answer-trace-close autofocus>關閉</button>
        </div>
        <div id="answerTraceBody" class="answer-trace-body"></div>
      </div>`;
    modal.addEventListener('click', (event) => {
      if (event.target.closest('[data-answer-trace-close]')) close();
    });
    modal.addEventListener('close', () => { requestVersion += 1; });
    document.body.appendChild(modal);
    return modal;
  }

  function close() {
    document.getElementById('answerTraceModal')?.close();
  }

  function field(label, value) {
    const alarmApp = app();
    return `<div class="answer-trace-field"><span>${alarmApp.esc(label)}</span><b>${alarmApp.esc(value || '未提供')}</b></div>`;
  }

  function render(answer) {
    const alarmApp = app();
    const modal = ensureModal();
    const state = VALID_STATES.has(answer.answer_state) ? answer.answer_state : 'complete';
    const date = answer.created_at ? new Date(answer.created_at) : null;
    const created = date && !Number.isNaN(date.getTime()) ? date.toLocaleString('zh-TW', { hour12: false }) : '未提供';
    const elapsed = answer.elapsed_ms != null && Number.isFinite(Number(answer.elapsed_ms))
      ? `${(Number(answer.elapsed_ms) / 1000).toLocaleString('zh-TW', { maximumFractionDigits: 2 })} 秒` : '未提供';
    const citations = Array.isArray(answer.citations) ? answer.citations : [];
    const citationHtml = citations.length
      ? citations.map((citation, index) => `<li><div class="answer-trace-citation-title"><span class="answer-trace-citation-number">${index + 1}</span><b>${alarmApp.esc(citation.code || citation.title || `引用來源 ${index + 1}`)}</b></div><div class="answer-trace-source">${alarmApp.esc(citation.source_file || citation.source || '未提供檔名')}${citation.locator || citation.page ? ` · ${alarmApp.esc(citation.locator || `第 ${citation.page} 頁`)}` : ''}</div></li>`).join('')
      : '<li class="answer-trace-empty">此回答沒有引用來源</li>';
    modal.querySelector('#answerTraceBody').innerHTML = `
      <div class="answer-trace-meta">
        <span class="answer-trace-state state-${state}">${STATE_LABELS[state]}</span>
        <span>產生時間：${alarmApp.esc(created)}</span><span>回答耗時：${alarmApp.esc(elapsed)}</span>
      </div>
      <section><h3>使用者問題</h3><div class="answer-trace-text answer-trace-question">${alarmApp.esc(answer.query || '未提供問題內容')}</div></section>
      <section><h3>AI 回答</h3><div class="answer-trace-text">${alarmApp.esc(answer.answer || '未提供回答內容')}</div></section>
      <section><h3>引用來源（${citations.length}）</h3><ul class="answer-trace-citations">${citationHtml}</ul></section>
      <details class="answer-trace-technical"><summary>技術資訊</summary><div class="answer-trace-grid">
        ${field('回答編號', answer.answer_id)}${field('模型服務', answer.provider)}${field('使用模型', answer.model)}
        ${field('斷詞版本', answer.tokenizer_version)}${field('檢索版本', answer.retrieval_version)}
      </div></details>`;
  }

  function renderUnavailable(answerId, message) {
    render({ answer_id: answerId, answer_state: 'unavailable', answer: message || '回答快照目前無法取得。', citations: [] });
  }

  async function open(answerId) {
    const alarmApp = app();
    const modal = ensureModal();
    const version = ++requestVersion;
    modal.querySelector('#answerTraceBody').innerHTML = '<p class="answer-trace-empty" role="status">正在載入回答快照…</p>';
    if (!modal.open) modal.showModal();
    modal.querySelector('#answerTraceBody').scrollTop = 0;
    try {
      const data = await alarmApp.apiJson(`/rag/answers/${encodeURIComponent(answerId)}`);
      if (version !== requestVersion || !modal.open) return;
      if (data?.status !== 'ok' || !data.answer) {
        renderUnavailable(answerId, data?.message || '回答快照不存在。');
        return;
      }
      render(data.answer);
    } catch (error) {
      if (version !== requestVersion || !modal.open) return;
      renderUnavailable(answerId, alarmApp.formatError(error, '回答快照無法取得。'));
    }
  }

  global.AnswerTrace = { open, close };
})(window);
