(() => {
  const runs = new WeakMap();

  function element(tag, text) {
    const node = document.createElement(tag);
    node.textContent = text;
    return node;
  }

  async function previewExcel({ input, result, request, onSuccess, formatError, kind = 'work_orders' }) {
    const users = kind === 'users';
    const endpoint = users ? '/users/import-excel' : '/work-orders/import-excel';
    const label = users ? '帳號' : '工單';
    const file = input.files?.[0];
    if (!file || !result || input.disabled) return;
    const run = {};
    runs.set(result, run);
    const current = () => runs.get(result) === run;
    const upload = (token) => {
      const body = new FormData();
      body.append('file', file);
      if (token) body.append('preview_token', token);
      return { method: 'POST', body };
    };
    result.className = 'excel-result show';
    result.textContent = `正在預覽：${file.name}`;
    try {
      const preview = await request(`${endpoint}/preview`, upload());
      if (!current()) return;
      if (preview.status !== 'ok') throw new Error(preview.message || '預覽失敗');
      result.replaceChildren(element('p', `${file.name}：可匯入 ${preview.valid} 筆，錯誤略過 ${preview.skipped} 筆${users ? '' : `，待審核知識 ${preview.candidate_count} 筆`}。尚未寫入。`));
      result.append(element('p', users ? '確認後只建立有效列；不覆寫既有帳號。新帳號首次登入必須更換密碼；預覽與履歷不顯示密碼。' : '確認後只匯入有效列。已匯入的來源紀錄或相同內容會略過；不同事件請填寫不同的 source_record_id。指派欄位須填入啟用中的維修帳號 ID。'));
      for (const row of preview.rows) {
        const detail = document.createElement('details');
        const identity = users ? row.values.user_id || '缺少帳號' : row.values.alarm_code || '缺少代碼';
        const description = users ? `${row.values.name || ''} / ${row.values.role} / ${row.values.line_scope}` : `${row.values.machine_id || '未指定設備'} / ${row.values.manual} / ${row.values.status}`;
        detail.append(element('summary', `第 ${row.row} 列 · ${identity} · ${row.error ? `錯誤：${row.error}` : description}`));
        for (const warning of row.warnings) detail.append(element('p', `調整說明：${warning}`));
        const fields = document.createElement('dl');
        const labels = { user_id: '帳號', name: '姓名', role: '角色', team: '團隊', line_scope: '產線範圍', alarm_code: '警報／異常代碼', machine_id: '設備', manual: '知識庫', status: '狀態', priority: '優先級', assigned_to: '指派人員', description: '描述', resolution: '處理結果', notes: '備註', root_cause: '根本原因', repair_action: '維修動作', source: '來源', verified_by: '原驗證人員' };
        for (const [key, value] of Object.entries(row.values)) {
          if (key === 'password' || key === 'password_hash') continue;
          fields.append(element('dt', labels[key] || key), element('dd', value || '（空白）'));
        }
        detail.append(fields);
        result.append(detail);
      }
      const confirm = element('button', `確認匯入 ${preview.valid} 筆有效${label}`);
      confirm.type = 'button';
      confirm.className = 'wo-btn';
      confirm.disabled = !preview.valid;
      const cancel = element('button', '取消');
      cancel.type = 'button';
      cancel.className = 'wo-btn alt';
      cancel.addEventListener('click', () => {
        if (!current()) return;
        runs.delete(result);
        result.textContent = `已取消，未匯入任何${label}。`;
        input.value = '';
      });
      confirm.addEventListener('click', async () => {
        if (!current() || confirm.disabled) return;
        confirm.disabled = true;
        cancel.disabled = true;
        input.disabled = true;
        try {
          const data = await request(endpoint, upload(preview.preview_token));
          if (data.status !== 'ok') throw new Error(data.message || '匯入失敗');
          result.className = 'excel-result show ok';
          result.textContent = `匯入完成：新增 ${data.imported} 筆，略過 ${data.skipped} 筆${users ? '' : `，待審核知識 ${data.candidate_count} 筆`}。`;
          if (data.batch_id) result.append(element('p', `匯入批次：${data.batch_id}（可在資料匯入的履歷中查閱）`));
        } catch (error) {
          result.className = 'excel-result show err';
          result.textContent = `${formatError(error, 'Excel 匯入失敗')}；請重新選檔預覽。若連線中斷，請先查閱${label}與匯入履歷確認結果。`;
          return;
        } finally {
          input.disabled = false;
          input.value = '';
          runs.delete(result);
        }
        // Refresh failures must not misreport a committed import as failed.
        try { await onSuccess(); } catch (_) {
          result.append(element('p', `${label}已匯入，畫面更新失敗，請重新整理。`));
        }
      });
      result.append(confirm, cancel);
    } catch (error) {
      if (!current()) return;
      result.className = 'excel-result show err';
      result.textContent = formatError(error, 'Excel 預覽失敗');
    } finally {
      if (current()) input.value = '';
    }
  }
  window.previewWorkOrderExcel = options => previewExcel(options);
  window.previewUserExcel = options => previewExcel({ ...options, kind: 'users' });
})();
