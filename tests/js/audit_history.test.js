const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function load() {
  const context = { window: {}, document: { addEventListener() {} } };
  vm.createContext(context);
  for (const file of ['modules/audit.js', 'pages/maintenance.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../static/js', file), 'utf8'), context);
  }
  return context;
}

const created = { action: 'created', user_id: 'operator01',
  created_at: '2026-09-26T13:05:20.123456+00:00', to_status: 'open' };

test('knowledge ingestion history summarizes technical envelopes without guessing truncated results', () => {
  const audit = load().window.AlarmAudit;
  const value = { truncated: true, sha256: 'long-hash', excerpt: '{"auto_ingested":true,"unfinished' };
  const event = { changes: [
    { field: 'kb_ingest_result', from: '', to: value },
    { field: 'kb_ingested_at', from: '', to: '2026-09-28T04:35:44.937578' },
  ] };
  const original = JSON.stringify(event);
  const html = audit.renderChanges({ esc: String }, event);
  assert.match(html, /知識庫寫入結果.*已記錄入庫處理結果/);
  assert.match(html, /知識庫寫入時間.*2026\/09\/28 04:35:44/);
  assert.doesNotMatch(html, /sha256|auto_ingested|kb_ingest|已寫入知識庫/);
  assert.equal(JSON.stringify(event), original);
  assert.equal(audit.changeValue('kb_ingest_result', {auto_ingested: true, response: {sections_added: 1}, validation: {retrieval_hit: false}}),
    '已寫入知識庫；新增 1 段知識內容；檢索驗證未命中');
  assert.equal(audit.changeValue('kb_ingest_result', {auto_ingested: false}), '尚未完成知識庫寫入');
  assert.equal(audit.changeValue('notes', {truncated: true, excerpt: '[Supervisor rework] test', sha256: 'abc'}),
    '[主管退回重工] test…（內容較長，僅顯示稽核摘要）');
  assert.equal(audit.changeValue('verified_at', '2026-09-28T12:35:44.93+08:00'), '2026/09/28 12:35:44+08:00');
});

test('shared timeline translations preserve source data and escape free text', () => {
  const context = load();
  const audit = context.window.AlarmAudit;
  const event = { action: 'work_order_synced', audit_source: 'issue', changes: [
    { field: 'kb_candidate', from: true, to: false },
    { field: 'kb_review_status', from: 'pending_review', to: 'not_ready' },
    { field: 'operator_note', from: '', to: '[Supervisor rework] <script>保留文字</script>' },
    { field: 'future_field', from: '', to: 'future_value' },
  ] };
  const original = JSON.stringify(event);
  const app = { esc: value => String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;') };
  const html = audit.renderChanges(app, event);
  assert.match(html, /知識候選<\/b>：是 → 否/);
  assert.match(html, /知識審核狀態<\/b>：待審核 → 尚未就緒/);
  assert.match(html, /主管退回重工.*&lt;script&gt;保留文字/);
  assert.match(html, /future_field.*future_value/);
  assert.equal(audit.actionLabel('created', 'issue'), '建立問題');
  assert.equal(audit.actionLabel('created', 'work order'), '建立工單');
  assert.equal(audit.actionLabel(event.action, event.audit_source), '同步工單狀態');
  assert.equal(JSON.stringify(event), original);
});

test('repeated stored creation events appear once per entity without changing history', () => {
  const audit = load().window.AlarmAudit;
  const history = [created, { ...created, _request_id: 'create:issue:1' },
    { ...created, from_status: '', fields: [], changes: [], _request_id: 'legacy:1' }];
  const before = JSON.stringify(history);
  assert.equal(audit.uniqueEvents(history).length, 1);
  const merged = audit.mergeEvents(history, history);
  assert.equal(merged.length, 2); // Creating an issue and a work order are distinct actions.
  assert.equal(JSON.stringify(history), before);
});

test('different actors, times, changes and undated events remain visible', () => {
  const audit = load().window.AlarmAudit;
  const history = [created, { ...created, user_id: 'operator02' },
    { ...created, created_at: '2026-09-26T13:05:20.123457+00:00' },
    { ...created, to_status: 'assigned' }, { ...created, action: 'updated' },
    { ...created, changes: [{ field: 'notes', to: 'extra context' }] },
    { ...created, source_id: 'another-issue' }, {}, {}];
  assert.equal(audit.uniqueEvents(history).length, history.length);
});

test('timeline keeps newest first and shows a status transition only in its heading', () => {
  const audit = load().window.AlarmAudit;
  const event = { action: 'status_changed', from_status: 'assigned', to_status: 'in_progress',
    created_at: '2026-09-26T13:11:05+00:00', changes: [
      { field: 'status', from: 'assigned', to: 'in_progress' },
      { field: 'accepted_by', from: '', to: 'maintenance01' }] };
  assert.equal(audit.mergeEvents([created, event], [created])[0].action, 'status_changed');
  const html = audit.renderChanges({ esc: String }, event);
  assert.doesNotMatch(html, /status:/);
  assert.match(html, /接受人員<\/b>：- → maintenance01/);
  assert.match(audit.renderChanges({ esc: String }, { changes: event.changes }), /狀態<\/b>：已指派 → 處理中/);
});

test('maintenance context does not repeat the form description but retains a changed original', () => {
  const context = load();
  const box = { innerHTML: '' };
  const issue = { issue_id: 'ISS-1', original_description: 'MOCK observation BLUE',
    source: 'operator', line_id: 'line-a', status: 'in_progress' };
  context.window.AlarmApp = { $: () => box, getState: () => [issue],
    esc: value => String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;') };
  context.renderMaintenanceIssueContext({ issue_id: 'ISS-1', description: issue.original_description });
  assert.doesNotMatch(box.innerHTML, /MOCK observation BLUE|ISS-1/);
  assert.match(box.innerHTML, /line-a/);
  issue.original_description = '<original symptom>';
  context.renderMaintenanceIssueContext({ issue_id: 'ISS-1', description: 'updated diagnosis' });
  assert.match(box.innerHTML, /&lt;original symptom&gt;/);
  assert.doesNotMatch(box.innerHTML, /<original symptom>/);
});

const assigned = {
  action: 'status_changed', user_id: 'supervisor01',
  created_at: '2026-09-26T13:09:37.151086+00:00',
  from_status: 'pending', to_status: 'assigned', changes: [
    { field: 'assigned_to', from: '', to: 'maintenance01' },
    { field: 'status', from: 'pending', to: 'assigned' }],
};
const assignmentSync = {
  action: 'work_order_synced', user_id: 'supervisor01',
  created_at: '2026-09-26T13:09:37.219769+00:00',
  from_status: 'open', to_status: 'assigned', changes: [
    { field: 'assigned_to', from: '', to: 'maintenance01' },
    { field: 'status', from: 'open', to: 'assigned' }],
};

test('one assignment and its immediate issue mirror display as one operation', () => {
  const audit = load().window.AlarmAudit;
  const before = JSON.stringify(assignmentSync);
  const events = audit.mergeEvents([assigned], [assignmentSync]);
  assert.equal(events.length, 1);
  assert.equal(events[0].audit_source, 'work order');
  assert.equal(events[0].changes.length, 2);
  assert.equal(JSON.stringify(assignmentSync), before);
});

test('issue-only changes, different actors, delayed or ambiguous syncs remain visible', () => {
  const audit = load().window.AlarmAudit;
  for (const sync of [
    { ...assignmentSync, changes: [...assignmentSync.changes, { field: 'description', from: 'a', to: 'b' }] },
    { ...assignmentSync, user_id: 'supervisor02' },
    { ...assignmentSync, created_at: '2026-09-26T13:09:40Z' },
    { ...assignmentSync, created_at: '2026-09-26T13:09:36Z' },
    { ...assignmentSync, created_at: '' },
    { ...assignmentSync, to_status: 'completed' },
    { ...assignmentSync, changes: [] },
  ]) assert.equal(audit.mergeEvents([assigned], [sync]).length, 2);
  assert.equal(audit.mergeEvents([], [assignmentSync]).length, 1);
  const another = { ...assigned, created_at: '2026-09-26T13:09:37.160000+00:00' };
  assert.equal(audit.mergeEvents([assigned, another], [assignmentSync]).length, 3);
  const secondSync = { ...assignmentSync, created_at: '2026-09-26T13:09:37.300000+00:00' };
  assert.equal(audit.mergeEvents([assigned], [assignmentSync, secondSync]).length, 2);
});

test('a mirrored resolution retains the original work-order details', () => {
  const audit = load().window.AlarmAudit;
  const order = { ...assigned, changes: [{ field: 'resolution', from: '', to: 'MOCK checked' }] };
  const sync = { ...assignmentSync, changes: [{ field: 'resolution_summary', from: '', to: 'MOCK checked' }] };
  assert.equal(audit.mergeEvents([order], [sync]).length, 1);
});
