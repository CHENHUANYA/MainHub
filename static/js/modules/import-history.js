(() => {
  const runs = new WeakMap();
  const node = (tag, text) => {
    const element = document.createElement(tag);
    element.textContent = text;
    return element;
  };
  window.renderImportHistory = async ({ target, request, kind = '', offset = 0 }) => {
    const run = {};
    runs.set(target, run);
    target.textContent = '載入匯入履歷…';
    try {
      const data = await request(`/imports/batches?limit=20&offset=${offset}&kind=${encodeURIComponent(kind)}`);
      if (runs.get(target) !== run) return;
      if (data.status !== 'ok') throw new Error(data.message || '履歷載入失敗');
      const count = node('p', data.total ? `共 ${data.total} 批，顯示 ${offset + 1}–${offset + data.batches.length}` : '尚無匯入履歷');
      count.className = 'import-history-count';
      target.replaceChildren(count);
      for (const batch of data.batches) {
        const detail = document.createElement('details');
        detail.className = 'role-row import-batch';
        const type = batch.kind === 'users' ? '人員' : '工單';
        const status = batch.status === 'completed' ? '已完成' : '未寫入';
        const timestamp = new Date(batch.created_at).toLocaleString('zh-TW', { hour12: false });
        const summary = document.createElement('summary');
        const heading = node('span', '');
        heading.className = 'import-batch-heading';
        const filename = node('strong', batch.filename);
        const badge = node('span', status);
        badge.className = `import-batch-status ${batch.status === 'completed' ? 'is-complete' : ''}`;
        heading.append(filename, badge);
        const meta = node('span', `${type} · ${timestamp} · 新增 ${batch.imported}／略過 ${batch.skipped}`);
        meta.className = 'import-batch-meta';
        summary.append(heading, meta);
        detail.append(summary);
        detail.append(node('p', `批次：${batch.batch_id}；執行人員：${batch.actor}`));
        detail.append(node('p', `檔案 SHA256：${batch.file_sha256}`));
        if (batch.error) detail.append(node('p', batch.error));
        const rows = node('div', '展開後載入逐列結果');
        detail.append(rows);
        let loaded = false;
        detail.addEventListener('toggle', async () => {
          if (!detail.open || loaded) return;
          loaded = true;
          try {
            const result = await request(`/imports/batches/${encodeURIComponent(batch.batch_id)}`);
            if (result.status !== 'ok') throw new Error(result.message || '逐列結果載入失敗');
            rows.replaceChildren();
            for (const row of result.batch.rows) {
              rows.append(node('p', `第 ${row.row} 列：${row.error || `已新增 ${row.record_id}`}`));
              for (const warning of row.warnings || []) rows.append(node('p', warning));
            }
            if (!result.batch.rows.length) rows.append(node('p', '確認未通過或儲存失敗，未提交任何資料。'));
          } catch (error) {
            rows.textContent = error.message;
            loaded = false;
          }
        });
        target.append(detail);
      }
      const pagination = document.createElement('nav');
      pagination.className = 'import-history-pagination';
      pagination.setAttribute('aria-label', '匯入履歷分頁');
      for (const [label, next, disabled] of [['上一頁', Math.max(0, offset - 20), offset === 0],
                                           ['下一頁', offset + 20, offset + 20 >= data.total]]) {
        const button = node('button', label);
        button.type = 'button'; button.className = 'wo-btn alt'; button.disabled = disabled;
        button.addEventListener('click', () => window.renderImportHistory({ target, request, kind, offset: next }));
        pagination.append(button);
      }
      if (data.total > 20) target.append(pagination);
    } catch (error) {
      if (runs.get(target) === run) target.textContent = error.message || '履歷載入失敗';
    }
  };
})();
