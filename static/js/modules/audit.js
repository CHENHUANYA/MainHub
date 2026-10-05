(function initAlarmAudit() {
  const statusLabels = { open: '未處理', pending: '待處理', assigned: '已指派',
    in_progress: '處理中', completed: '待驗證', verified: '已驗證', cancelled: '已取消' };
  const actionLabels = { updated: '更新紀錄', status_changed: '變更狀態',
    work_order_synced: '同步工單狀態', issue_synced: '同步問題狀態',
    operator_note_added: '新增補充說明', work_order_created: '建立工單',
    knowledge_approve: '核准知識', knowledge_needs_revision: '退回知識補充',
    knowledge_reject: '不採用知識', import_status_override: '匯入狀態更新' };
  const fieldLabels = { status: '狀態', description: '問題描述', original_description: '原始描述',
    root_cause: '根本原因', repair_action: '實際維修動作', resolution: '處理結果',
    resolution_summary: '處理結果摘要', notes: '備註', operator_note: '補充說明',
    assigned_to: '負責人', accepted_by: '接受人員', completed_by: '完成人員',
    verified_by: '驗證人員', created_by: '建立人員', updated_by: '更新人員',
    created_at: '建立時間', updated_at: '更新時間', completed_at: '完成時間', verified_at: '驗證時間',
    priority: '優先等級', severity: '嚴重度', failure_category: '故障分類',
    machine_id: '機台', line_id: '產線', alarm_code: '警報代碼', manual: '手冊',
    source: '來源', work_order_id: '工單編號', issue_id: '問題編號',
    kb_candidate: '知識候選', kb_review_status: '知識審核狀態', kb_review_note: '知識審核說明',
    kb_reviewed_by: '知識審核人員', kb_reviewed_at: '知識審核時間',
    kb_ingest_result: '知識庫寫入結果', kb_ingested_at: '知識庫寫入時間', kb_duplicate_of: '可能重複的工單',
    llm_expected_fix: 'LLM 建議修正', llm_missing_info: 'LLM 缺漏資訊', llm_feedback: 'LLM 回饋',
    llm_correctness: 'LLM 正確率回饋', llm_coverage: 'LLM 覆蓋率回饋' };
  const reviewLabels = { not_ready: '尚未就緒', pending_review: '待審核', approved: '已核准',
    needs_revision: '待補充', rejected: '不採用', ingested: '已加入知識庫', validation_failed: '驗證未通過' };
  const priorityLabels = { critical: '緊急', high: '高', medium: '中', low: '低' };
  const sourceLabels = { issue: '問題', 'work order': '工單', operator: '操作員',
    maintenance: '維修人員', supervisor: '主管', admin: '管理員', manual: '人工建立', machine: '機器事件' };
  const label = (value, labels) => Object.hasOwn(labels, value) ? labels[value] : (value || '-');
  const statusLabel = (value) => label(value, statusLabels);
  const sourceLabel = (value) => label(value, sourceLabels);
  function actionLabel(action, source) {
    if (action === 'created') return source === 'issue' ? '建立問題' : '建立工單';
    return label(action || 'updated', actionLabels);
  }
  function displayNote(value) {
    return String(value || '').replaceAll('[Operator follow-up]', '[操作員補充]')
      .replaceAll('[Supervisor rework]', '[主管退回重工]');
  }
  function changeValue(field, value) {
    if (value === null || value === undefined || value === '') return '-';
    if (field === 'kb_ingest_result') {
      // Truncated audit envelopes are not complete JSON. Never infer success from their excerpt.
      if (value.truncated === true) return '已記錄入庫處理結果（稽核紀錄保留摘要）';
      const parts = [value.auto_ingested === true ? '已寫入知識庫'
        : value.auto_ingested === false ? '尚未完成知識庫寫入' : '已記錄入庫處理結果'];
      const sections = value.response?.sections_added;
      if (Number.isInteger(sections) && sections >= 0) parts.push(`新增 ${sections} 段知識內容`);
      if (value.validation?.retrieval_hit === true) parts.push('檢索驗證已命中');
      if (value.validation?.retrieval_hit === false) parts.push('檢索驗證未命中');
      return parts.join('；');
    }
    if (value.truncated === true && typeof value.excerpt === 'string') {
      const excerpt = field === 'notes' || field === 'operator_note' ? displayNote(value.excerpt) : value.excerpt;
      return `${excerpt}…（內容較長，僅顯示稽核摘要）`;
    }
    // Preserve the recorded clock and any timezone offset; do not guess a zone for legacy values.
    if (field.endsWith('_at') && typeof value === 'string') {
      return value.replace(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?/, '$1/$2/$3 $4');
    }
    if (field === 'status') return statusLabel(value);
    if (field === 'kb_review_status') return label(value, reviewLabels);
    if (field === 'priority' || field === 'severity') return label(value, priorityLabels);
    if (field === 'source') return sourceLabel(value);
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (typeof value === 'object') return JSON.stringify(value);
    if (field === 'notes' || field === 'operator_note') return displayNote(value);
    return String(value);
  }
  function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === 'object') {
      return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
    }
    return value;
  }

  function uniqueEvents(history) {
    const seen = new Set();
    return (Array.isArray(history) ? history : []).filter((event) => {
      // Ignore storage IDs, but retain source, actor, precise timestamp and all
      // event details. Undated records cannot safely be treated as duplicates.
      if (!event.created_at) return true;
      const { _request_id, ...content } = event;
      const key = JSON.stringify(canonical({ ...content,
        from_status: event.from_status || '', to_status: event.to_status || '',
        fields: event.fields || [], changes: event.changes || [],
      }));
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function renderChanges(app, event) {
    const changes = (Array.isArray(event?.changes) ? event.changes : []).filter((change) =>
      // The transition is already shown in the event heading.
      !(change.field === 'status' && (event.from_status || event.to_status)
        && change.from === event.from_status && change.to === event.to_status));
    if (!app || !changes.length) {
      return '';
    }
    return `<div class="audit-fields">${changes.map((change) => {
      const field = app.esc(label(change.field, fieldLabels));
      const before = app.esc(changeValue(change.field, change.from));
      const after = app.esc(changeValue(change.field, change.to));
      return `<div><b>${field}</b>：${before} → ${after}</div>`;
    }).join('')}</div>`;
  }

  function mergeEvents(workOrderHistory, issueHistory) {
    const workOrderEvents = Array.isArray(workOrderHistory)
      ? workOrderHistory.map((event) => ({ ...event, audit_source: 'work order' }))
      : [];
    const issueEvents = Array.isArray(issueHistory)
      ? issueHistory.map((event) => ({ ...event, audit_source: 'issue' }))
      : [];
    const events = uniqueEvents([...workOrderEvents, ...issueEvents]);
    const matchedOrders = new Set();
    const normalizeChange = (change) => {
      const field = change.field === 'resolution_summary' ? 'resolution' : change.field;
      const status = (value) => field === 'status' && value === 'open' ? 'pending' : value;
      return JSON.stringify(canonical({ ...change, field,
        from: status(change.from), to: status(change.to) }));
    };
    const visible = events.filter((event) => {
      if (event.audit_source !== 'issue' || event.action !== 'work_order_synced'
          || !event.user_id || !event.changes?.length) return true;
      // A work-order save also mirrors changes onto its linked issue. Fold only
      // an unambiguous, immediate mirror whose every change is already visible.
      // Raw histories remain intact; unrelated and ambiguous events stay visible.
      const candidates = events.filter((order) => {
        if (order.audit_source !== 'work order' || order.user_id !== event.user_id) return false;
        const elapsed = Date.parse(event.created_at) - Date.parse(order.created_at);
        if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed > 1000) return false;
        const normalizeStatus = (value) => value === 'open' ? 'pending' : (value || '');
        if (normalizeStatus(event.from_status) !== normalizeStatus(order.from_status)
            || normalizeStatus(event.to_status) !== normalizeStatus(order.to_status)) return false;
        const changes = new Set((order.changes || []).map(normalizeChange));
        return event.changes.every((change) => changes.has(normalizeChange(change)));
      });
      if (candidates.length !== 1 || matchedOrders.has(candidates[0])) return true;
      matchedOrders.add(candidates[0]);
      return false;
    });
    return visible.sort((left, right) => {
      const leftTime = new Date(left.created_at || 0).getTime() || 0;
      const rightTime = new Date(right.created_at || 0).getTime() || 0;
      return rightTime - leftTime;
    });
  }

  window.AlarmAudit = {
    statusLabel, sourceLabel, actionLabel, changeValue, displayNote,
    uniqueEvents,
    renderChanges,
    mergeEvents,
  };
})();
