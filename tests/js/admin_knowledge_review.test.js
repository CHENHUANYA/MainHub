const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function setup() {
  const state = new Map();
  const elements = new Map();
  const calls = [];
  const app = {
    esc: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
    $(id) {
      if (!elements.has(id)) {
        const classes = new Set(['u-hidden']);
        elements.set(id, {
          value: '', textContent: '', disabled: false,
          focus() { this.focused = true; }, scrollIntoView() {},
          showModal() { this.open = true; }, close() { this.open = false; },
          classList: {
            add: c => classes.add(c), remove: c => classes.delete(c),
            contains: c => classes.has(c),
            toggle(c, enabled) { if (enabled) classes.add(c); else classes.delete(c); },
          },
        });
      }
      return elements.get(id);
    },
    getState: key => state.get(key),
    setState: (key, value) => state.set(key, value),
    apiJson: async (url, options) => { calls.push({ url, options }); return { status: 'ok' }; },
    formatError: error => error.message,
    setResultMessage: (el, css, message) => { el.textContent = message; },
  };
  const trigger = { focus() { this.focused = true; } };
  const context = {
    document: { addEventListener() {}, activeElement: trigger, contains: el => el === trigger },
    window: {
      AlarmApp: app,
      prompt() { throw new Error('Native prompt must not be used'); },
      confirm() { throw new Error('Native confirm must not be used'); },
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../static/js/pages/admin.js'), 'utf8'), context);
  let reloads = 0;
  context.loadAdminConsole = async () => { reloads += 1; };
  return { app, calls, context, state, trigger, reloads: () => reloads };
}

test('view work order opens the requested record read-only and escapes stored content', () => {
  const { app, calls, context, state } = setup();
  state.set('adminWorkOrders', [{ id: 'WO-1', machine_id: 'CNC-01', notes: '<script>bad()</script>', status: 'verified', kb_review_status: 'ingested' }]);
  const item = { work_order_id: 'WO-1', type: 'work_order', kb_review_status: 'ingested' };
  const row = context.renderAdminQualityItem(app, item);
  assert.match(row, /data-on-click="openAdminWorkOrder"/);
  assert.doesNotMatch(row, /selectAdminSection/);
  context.openAdminWorkOrder('WO-1');
  assert.equal(app.$('adminWorkOrderDialog').open, true);
  assert.equal(app.$('adminWorkOrderTitle').textContent, '工單 WO-1');
  assert.match(app.$('adminWorkOrderContent').innerHTML, /CNC-01/);
  assert.match(app.$('adminWorkOrderContent').innerHTML, /&lt;script&gt;/);
  assert.doesNotMatch(app.$('adminWorkOrderContent').innerHTML, /<script>|<input|<textarea/);
  context.closeAdminWorkOrder();
  assert.equal(app.$('adminWorkOrderDialog').open, false);
  context.openAdminWorkOrder('missing');
  assert.match(app.$('adminWorkOrderContent').textContent, /找不到/);
  assert.equal(calls.length, 0);
});

test('all review actions open the inline confirmation without writing; cancel restores focus', () => {
  const { app, calls, context, trigger } = setup();
  for (const action of ['needs_revision', 'reject', 'approve']) {
    context.reviewAdminKnowledge('WO-1', action, 7);
    assert.equal(app.$('adminKnowledgeReviewForm').classList.contains('u-hidden'), false);
    assert.equal(app.$('adminKnowledgeReviewNoteField').classList.contains('u-hidden'), action === 'approve');
    assert.equal(app.$('adminKnowledgeReviewNote').required, action === 'needs_revision');
    context.cancelAdminKnowledgeReview();
    assert.equal(app.$('adminKnowledgeReviewForm').classList.contains('u-hidden'), true);
    assert.equal(trigger.focused, true);
  }
  assert.equal(calls.length, 0);
});

test('revision requires a nonblank reason before sending', async () => {
  const { app, calls, context } = setup();
  context.reviewAdminKnowledge('WO-1', 'needs_revision', 7);
  app.$('adminKnowledgeReviewNote').value = '  ';
  await context.submitAdminKnowledgeReview();
  assert.equal(calls.length, 0);
  assert.match(app.$('adminKnowledgeReviewError').textContent, /請填寫/);
});

test('pending submit prevents duplicate requests, cancellation and target changes; failure preserves reason', async () => {
  const { app, calls, context, state, reloads } = setup();
  let fail;
  app.apiJson = (url, options) => {
    calls.push({ url, options });
    return new Promise((resolve, reject) => { fail = reject; });
  };
  context.reviewAdminKnowledge('WO/1', 'needs_revision', 7);
  app.$('adminKnowledgeReviewNote').value = '  Please document the cause  ';
  const pending = context.submitAdminKnowledgeReview();
  await context.submitAdminKnowledgeReview();
  context.cancelAdminKnowledgeReview();
  context.reviewAdminKnowledge('WO-2', 'reject', 3);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/work-orders/WO%2F1/knowledge-review');
  assert.deepEqual(JSON.parse(calls[0].options.body), { action: 'needs_revision', note: 'Please document the cause', version: 7 });
  assert.equal(state.get('adminKnowledgeReview').workOrderId, 'WO/1');
  assert.equal(app.$('adminKnowledgeReviewSubmit').disabled, true);
  assert.equal(app.$('adminKnowledgeReviewCancel').disabled, true);
  fail(new Error('Version conflict'));
  await pending;
  assert.equal(app.$('adminKnowledgeReviewError').textContent, 'Version conflict');
  assert.equal(app.$('adminKnowledgeReviewNote').value, '  Please document the cause  ');
  assert.equal(app.$('adminKnowledgeReviewForm').classList.contains('u-hidden'), false);
  assert.equal(app.$('adminKnowledgeReviewSubmit').disabled, false);
  assert.equal(app.$('adminKnowledgeReviewNote').disabled, false);
  assert.equal(reloads(), 1);
});

for (const action of ['needs_revision', 'reject', 'approve']) {
  test(`${action} submits the selected version and closes only after success`, async () => {
    const { app, calls, context, state, reloads } = setup();
    context.reviewAdminKnowledge('WO-1', action, 7);
    app.$('adminKnowledgeReviewNote').value = action === 'needs_revision' ? ' Add the missing steps ' : '';
    await context.submitAdminKnowledgeReview();
    assert.deepEqual(JSON.parse(calls[0].options.body), {
      action, note: action === 'needs_revision' ? 'Add the missing steps' : '', version: 7,
    });
    assert.equal(state.get('adminKnowledgeReview'), null);
    assert.equal(state.get('adminKnowledgeReviewSubmitting'), false);
    assert.equal(app.$('adminKnowledgeReviewForm').classList.contains('u-hidden'), true);
    assert.match(app.$('adminQualityResult').textContent, /WO-1/);
    assert.equal(reloads(), 1);
  });
}
