const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function setup() {
  const elements = new Map();
  const calls = [];
  let ready;
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', hidden: id === 'initialPasswordForm', handlers: {},
      addEventListener(type, fn) { this.handlers[type] = fn; },
      querySelector: () => ({}), focus() {},
    });
    return elements.get(id);
  };
  const window = {
    location: { origin: 'http://localhost', href: 'http://localhost/login' },
    AlarmCoreApi: {
      async apiJson(url, options) {
        calls.push({ url, body: options?.body && JSON.parse(options.body) });
        if (url === '/auth/login') throw Object.assign(new Error('Change required'), { code: 'PASSWORD_CHANGE_REQUIRED' });
        return { status: 'ok', initial_password_configured: true };
      },
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../static/js/pages/login.js'), 'utf8'), {
    window, URL, URLSearchParams,
    document: { getElementById: get, addEventListener: (_, fn) => { ready = fn; } },
    localStorage: { setItem() { assert.fail('Password change must not write localStorage'); } },
  });
  ready();
  const submit = id => get(id).handlers.submit({ preventDefault() {} });
  return { get, calls, submit, window };
}

test('first login opens change form; mismatch sends nothing; success clears all passwords', async () => {
  const { get, calls, submit } = setup();
  get('loginUsername').value = 'admin01';
  get('loginPassword').value = 'Initial-12345';
  await submit('loginForm');
  assert.equal(get('loginForm').hidden, true);
  assert.equal(get('initialPasswordForm').hidden, false);
  get('initialNewPassword').value = 'Personal-54321';
  get('initialConfirmPassword').value = 'Different-123';
  await submit('initialPasswordForm');
  assert.equal(calls.filter(c => c.url === '/auth/initial-password').length, 0);
  get('initialConfirmPassword').value = 'Personal-54321';
  await submit('initialPasswordForm');
  assert.deepEqual(calls.at(-1).body, {
    username: 'admin01', current_password: 'Initial-12345', new_password: 'Personal-54321',
  });
  for (const id of ['loginPassword', 'initialNewPassword', 'initialConfirmPassword']) assert.equal(get(id).value, '');
  assert.equal(get('initialPasswordForm').hidden, true);
  assert.equal(get('loginForm').hidden, false);
});

test('failed change keeps form available; cancelling clears entered secrets', async () => {
  const { get, submit, window } = setup();
  get('loginUsername').value = 'tech';
  get('loginPassword').value = 'Initial-12345';
  await submit('loginForm');
  get('initialNewPassword').value = 'Personal-54321';
  get('initialConfirmPassword').value = 'Personal-54321';
  window.AlarmCoreApi.apiJson = async () => { throw new Error('Try again'); };
  await submit('initialPasswordForm');
  assert.equal(get('initialPasswordResult').textContent, '暫時無法設定密碼，請確認網路連線後再試。');
  assert.equal(get('initialPasswordForm').hidden, false);
  assert.equal(get('initialPasswordSubmit').disabled, false);
  get('initialPasswordCancel').handlers.click();
  assert.equal(get('loginPassword').value, '');
  assert.equal(get('initialNewPassword').value, '');
  assert.equal(get('loginForm').hidden, false);
});
