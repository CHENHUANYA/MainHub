const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function load(file, role) {
  const order = { id: 'WO-1', version: 7, status: 'in_progress' };
  const state = new Map([['maintenanceOrders', [order]], ['supervisorOrders', [order]],
    ['maintenanceCurrentOrderId', 'WO-1'], ['woCurrentId', 'WO-1'], ['woCurrentVersion', 7]]);
  const elements = new Proxy({}, { get: (target, id) => target[id] ||= ({ value: id.endsWith('Status') ? 'completed' : 'MOCK value',
    classList: { add() {}, remove() {} }, focus() {}, scrollIntoView() {} }) });
  const calls = [];
  const app = { $: id => elements[id], getState: key => state.get(key), setState: (key, value) => state.set(key, value),
    currentUserId: () => role, formatError: e => String(e), apiJson: async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      return { status: 'ok', order };
    } };
  const context = { window: { AlarmApp: app, addEventListener() {}, alert() {} },
    document: { addEventListener() {}, querySelectorAll: () => [], querySelector: () => null }, console };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../', file), 'utf8'), context);
  vm.runInContext('loadMaintenanceData = async () => {}; loadSupervisorConsole = async () => {}; loadWorkOrders = async () => {}; loadCollectionDocuments = async () => {}; closeMaintenanceModal = () => {}; closeSupervisorReviewModal = () => {}; closeWoModal = () => {}; setSupervisorResult = () => {};', context);
  return { context, calls };
}

for (const [name, file, action] of [
  ['supervisor assignment', 'static/js/pages/supervisor.js', "patchSupervisorOrder(window.AlarmApp, 'WO-1', {assigned_to:'tech'})"],
  ['supervisor verification', 'static/js/pages/supervisor.js', "verifySupervisorOrder('WO-1')"],
  ['maintenance start', 'static/js/pages/maintenance.js', "startWorkOrder('WO-1')"],
  ['maintenance complete', 'static/js/pages/maintenance.js', 'saveMaintenanceWorkOrder()'],
  ['operations edit', 'static/js/modules/operations.js', 'saveWorkOrder()'],
]) {
  test(`${name} sends a version without server-managed identity fields`, async () => {
    const { context, calls } = load(file, 'test-user');
    await vm.runInContext(action, context);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].body.version, 7);
    for (const field of ['updated_by', 'accepted_by', 'completed_by', 'verified_by']) {
      assert.equal(Object.hasOwn(calls[0].body, field), false, field);
    }
  });
}

test('maintenance knowledge supplement sends only review content and version', async () => {
  const { context, calls } = load('static/js/pages/maintenance.js', 'test-user');
  const order = context.window.AlarmApp.getState('maintenanceOrders')[0];
  order.status = 'verified';
  order.kb_review_status = 'needs_revision';
  await vm.runInContext('saveMaintenanceWorkOrder()', context);
  assert.equal(calls.length, 1);
  assert.deepEqual(Object.keys(calls[0].body).sort(), ['notes', 'repair_action', 'resolution', 'root_cause', 'version']);
  assert.equal(calls[0].body.version, 7);
  assert.match(context.window.AlarmApp.$('mtWorkResult').textContent, /WO-1.*已補充並重新送審.*等待管理員審核/);
});

test('default maintenance board includes returned verified orders in the knowledge supplement column', () => {
  const { context } = load('static/js/pages/maintenance.js', 'test-user');
  const board = { dataset: {}, innerHTML: '' };
  const app = context.window.AlarmApp;
  const originalGet = app.$;
  app.$ = id => id === 'maintenanceWorkBoard' ? board : originalGet(id);
  vm.runInContext(`
    currentWorkFilters = () => ({view: 'active', priority: '', text: ''});
    workOrderCard = order => '<article>' + order.id + '</article>';
    renderWorkOrders(filterWorkOrders([
      {id: 'RETURNED', status: 'verified', kb_review_status: 'needs_revision'},
      {id: 'APPROVED', status: 'verified', kb_review_status: 'ingested'},
      {id: 'ACTIVE', status: 'in_progress'},
    ]));
  `, context);
  assert.match(board.innerHTML, /待補充知識/);
  assert.equal(board.innerHTML.split('<article>RETURNED</article>').length - 1, 1);
  assert.match(board.innerHTML, /ACTIVE/);
  assert.doesNotMatch(board.innerHTML, /APPROVED/);
});
