const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function setup() {
  const nodes = new Map();
  const calls = [];
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, {
      value: '', textContent: '', handlers: {}, disabled: false,
      addEventListener(name, handler) { this.handlers[name] = handler; },
      focus() {}, reset() { for (const n of nodes.values()) n.value = ''; },
    });
    return nodes.get(id);
  };
  const dialog = { open: false, handlers: {}, setAttribute() {},
    querySelector: selector => get(selector === 'form' ? 'passwordSettingsForm' : selector.slice(1)),
    addEventListener(name, handler) { this.handlers[name] = handler; },
    showModal() { this.open = true; }, close() { this.open = false; },
  };
  const window = { location: {}, AlarmCoreApi: { clearAuth() { calls.push('clear'); } },
    AlarmApp: { currentUserId: () => 'admin01', async apiJson(url, options) {
      calls.push({ url, body: JSON.parse(options.body) });
      return { status: 'ok' };
    } },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../static/js/modules/password-settings.js'), 'utf8'), {
    window, document: { activeElement: { focus() {} }, createElement: () => dialog, body: { appendChild() {} } },
    encodeURIComponent,
  });
  const submit = () => get('passwordSettingsForm').handlers.submit({ preventDefault() {} });
  function fill() {
    get('passwordCurrent').value = 'OriginalStrong!';
    get('passwordNew').value = 'PersonalStrong!';
    get('passwordConfirm').value = 'PersonalStrong!';
  }
  return { window, get, calls, dialog, submit, fill };
}

test('self change uses own endpoint, clears fields and authentication before redirect', async () => {
  const h = setup(); h.window.PasswordSettings.open(); h.fill();
  await h.submit();
  assert.deepEqual(h.calls[0], { url: '/auth/change-password', body: {
    current_password: 'OriginalStrong!', new_password: 'PersonalStrong!',
  } });
  assert.equal(h.calls[1], 'clear');
  assert.equal(h.get('passwordCurrent').value, '');
  assert.equal(h.dialog.open, false);
  assert.equal(h.window.location.href, '/login?password_changed=1');
});

test('mismatch and unchanged password do not submit; cancel clears secrets', async () => {
  const h = setup(); h.window.PasswordSettings.open(); h.fill();
  h.get('passwordConfirm').value = 'Mismatch!'; await h.submit();
  assert.equal(h.calls.length, 0);
  h.get('passwordNew').value = h.get('passwordConfirm').value = 'OriginalStrong!'; await h.submit();
  assert.equal(h.calls.length, 0);
  h.get('passwordSettingsCancel').handlers.click();
  assert.equal(h.get('passwordNew').value, '');
});

test('pending request blocks repeat submit, Escape and target switch; failure preserves input', async () => {
  const h = setup(); let reject;
  h.window.AlarmApp.apiJson = () => new Promise((_, fail) => { reject = fail; });
  h.window.PasswordSettings.open(); h.fill(); const request = h.submit();
  assert.equal(h.get('passwordSettingsSubmit').disabled, true);
  await h.submit(); h.dialog.handlers.cancel({ preventDefault() {} });
  h.window.PasswordSettings.openReset({ user_id: 'other' });
  assert.equal(h.dialog.open, true);
  assert.equal(h.get('passwordCurrentField').hidden, false);
  reject(new Error('目前密碼不正確')); await request;
  assert.equal(h.get('passwordSettingsResult').textContent, '目前密碼不正確');
  assert.equal(h.get('passwordNew').value, 'PersonalStrong!');
  assert.equal(h.get('passwordSettingsSubmit').disabled, false);
});

test('admin recovery submits temporary password and version only after confirmation', async () => {
  const h = setup(); let success = false;
  h.window.PasswordSettings.openReset({ user_id: 'operator01', updated_at: 'v2' }, () => { success = true; });
  assert.equal(h.calls.length, 0); h.fill(); await h.submit();
  assert.deepEqual(h.calls[0], { url: '/users/operator01/password', body: {
    password: 'PersonalStrong!', expected_updated_at: 'v2',
  } });
  assert.equal(success, true);
  assert.equal(h.window.location.href, undefined);
});

test('administrator cannot use recovery dialog to bypass own current password', () => {
  const h = setup(); h.window.PasswordSettings.openReset({ user_id: 'admin01' });
  assert.equal(h.get('passwordCurrentField').hidden, false);
  assert.equal(h.get('passwordCurrent').required, true);
});
