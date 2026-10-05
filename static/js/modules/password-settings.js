(() => {
  let dialog;
  let pending = false;
  let operation;
  let trigger;

  function close() {
    if (pending) return;
    dialog.querySelector('form').reset();
    dialog.close();
    trigger?.focus();
    operation = null;
  }

  function createDialog() {
    if (dialog) return;
    dialog = document.createElement('dialog');
    dialog.id = 'passwordSettingsDialog';
    dialog.className = 'password-settings-dialog';
    dialog.setAttribute('aria-labelledby', 'passwordSettingsTitle');
    dialog.innerHTML = `<form id="passwordSettingsForm">
      <h2 id="passwordSettingsTitle"></h2>
      <p id="passwordSettingsHint"></p>
      <label id="passwordCurrentField" for="passwordCurrent">目前密碼
        <input id="passwordCurrent" type="password" autocomplete="current-password" maxlength="1024">
      </label>
      <label for="passwordNew"><span id="passwordNewLabel">新密碼</span>
        <input id="passwordNew" type="password" autocomplete="new-password" minlength="8" maxlength="1024" required>
      </label>
      <label for="passwordConfirm">再次輸入密碼
        <input id="passwordConfirm" type="password" autocomplete="new-password" minlength="8" maxlength="1024" required>
      </label>
      <p id="passwordSettingsResult" role="alert" aria-live="polite"></p>
      <div class="password-settings-actions">
        <button type="submit" id="passwordSettingsSubmit">確認更改</button>
        <button type="button" id="passwordSettingsCancel">取消</button>
      </div>
    </form>`;
    document.body.appendChild(dialog);
    dialog.querySelector('#passwordSettingsCancel').addEventListener('click', close);
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    dialog.querySelector('form').addEventListener('submit', submit);
  }

  function open(resetUser = null, onSuccess = null) {
    if (pending) return;
    createDialog();
    const app = window.AlarmApp;
    if (resetUser?.user_id === app.currentUserId()) resetUser = null;
    trigger = document.activeElement;
    operation = { user: resetUser, onSuccess };
    const get = id => dialog.querySelector('#' + id);
    get('passwordSettingsForm').reset();
    get('passwordSettingsTitle').textContent = resetUser ? `發放臨時密碼：${resetUser.user_id}` : '更改自己的密碼';
    get('passwordSettingsHint').textContent = resetUser
      ? '請先確認本人身分，再將臨時密碼交給本人。原密碼與所有登入會失效；本人下次登入必須設定自己的新密碼。'
      : '請輸入目前密碼以確認身分。更改後所有裝置會登出，請使用新密碼重新登入。';
    get('passwordCurrentField').hidden = Boolean(resetUser);
    get('passwordCurrent').required = !resetUser;
    get('passwordNewLabel').textContent = resetUser ? '臨時密碼（至少 8 個字元）' : '新密碼（至少 8 個字元）';
    get('passwordSettingsSubmit').textContent = resetUser ? '確認發放臨時密碼' : '確認更改';
    get('passwordSettingsResult').textContent = '';
    if (!dialog.open) dialog.showModal();
    get(resetUser ? 'passwordNew' : 'passwordCurrent').focus();
  }

  async function submit(event) {
    event.preventDefault();
    if (pending || !operation) return;
    const get = id => dialog.querySelector('#' + id);
    const result = get('passwordSettingsResult');
    const current = get('passwordCurrent').value;
    const password = get('passwordNew').value;
    if (password !== get('passwordConfirm').value) {
      result.textContent = '兩次輸入的密碼不一致。';
      get('passwordConfirm').focus();
      return;
    }
    if (!operation.user && password === current) {
      result.textContent = '新密碼必須與目前密碼不同。';
      get('passwordNew').focus();
      return;
    }
    const { user, onSuccess } = operation;
    const button = get('passwordSettingsSubmit');
    const label = button.textContent;
    pending = true;
    button.disabled = true;
    get('passwordSettingsCancel').disabled = true;
    result.textContent = '正在處理…';
    try {
      const path = user ? `/users/${encodeURIComponent(user.user_id)}/password` : '/auth/change-password';
      const body = user ? { password, expected_updated_at: user.updated_at || null }
        : { current_password: current, new_password: password };
      await window.AlarmApp.apiJson(path, {
        method: user ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      get('passwordSettingsForm').reset();
      pending = false;
      close();
      if (user) {
        // A successful reset must not be reported as failed if refreshing the list fails.
        await onSuccess?.(user);
      } else {
        window.AlarmCoreApi.clearAuth();
        window.location.href = '/login?password_changed=1';
      }
    } catch (error) {
      result.textContent = error.status === 429 ? '嘗試次數過多，請稍後再試。' : (error.message || '密碼更改失敗，請再試一次。');
    } finally {
      pending = false;
      button.disabled = false;
      get('passwordSettingsCancel').disabled = false;
      button.textContent = label;
    }
  }

  function attach(pill) {
    if (pill.querySelector('.auth-change-password')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'auth-change-password';
    button.textContent = '更改密碼';
    button.addEventListener('click', () => open());
    pill.insertBefore(button, pill.querySelector('.auth-logout'));
  }
  window.PasswordSettings = { attach, open, openReset: (user, onSuccess) => open(user, onSuccess) };
})();
