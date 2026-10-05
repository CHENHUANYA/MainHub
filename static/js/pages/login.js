(() => {
  const TOKEN_KEY = 'alarmAuthToken';
  const USER_KEY = 'alarmAuthUser';
  const ROLE_NEXT_PATHS = {
    operator: new Set(['/operator', '/assistant']),
    maintenance: new Set(['/maintenance', '/assistant']),
    supervisor: new Set(['/supervisor', '/dashboard', '/assistant']),
    admin: new Set(['/admin', '/dashboard', '/assistant', '/operations']),
  };

  function $(id) {
    return document.getElementById(id);
  }

  function coreApi() {
    return window.AlarmCoreApi || {};
  }

  function setResult(message, state = 'error') {
    const result = $('loginResult');
    if (!result) {
      return;
    }
    result.className = `upload-result show ${state}`;
    result.textContent = message;
  }

  function setSubmitting(isSubmitting) {
    const button = $('loginSubmit');
    if (!button) {
      return;
    }
    button.disabled = isSubmitting;
    button.querySelector('span').textContent = isSubmitting ? '登入中...' : '登入';
  }

  function authErrorMessage(error, changingPassword = false) {
    if (error.status === 401 || error.message === 'Invalid username or password') {
      return changingPassword
        ? '帳號或臨時密碼不正確，請返回登入後重新輸入。'
        : '帳號或密碼不正確，請重新輸入。';
    }
    if (error.status === 429) return '嘗試次數過多，請稍候再試。';
    if (error.status >= 500) return '服務暫時無法使用，請稍候再試。';
    if (changingPassword && error.status === 400) {
      return '新密碼須與臨時密碼不同，至少 8 個字元，且不可使用常見預設密碼。';
    }
    if (changingPassword && error.status === 409) return '帳號資料已變更，請返回登入後重新操作。';
    if (error.status === 422) return '輸入資料不符合格式，請檢查後再試。';
    return changingPassword
      ? '暫時無法設定密碼，請確認網路連線後再試。'
      : '暫時無法登入，請確認網路連線後再試。';
  }

  function defaultPathForRole(role) {
    const api = coreApi();
    return api.roleHome ? api.roleHome(role) : '/dashboard';
  }

  function safeNextPath(rawNext, user) {
    const fallback = defaultPathForRole(user?.role);
    if (!rawNext) {
      return fallback;
    }
    try {
      const candidate = new URL(rawNext, window.location.origin);
      const allowedPaths = ROLE_NEXT_PATHS[user?.role] || new Set();
      if (candidate.origin !== window.location.origin || !allowedPaths.has(candidate.pathname)) {
        return fallback;
      }
      return `${candidate.pathname}${candidate.search}${candidate.hash}`;
    } catch (_) {
      return fallback;
    }
  }

  function nextPath(user) {
    const url = new URL(window.location.href);
    return safeNextPath(url.searchParams.get('next'), user);
  }

  function saveAuth(token, user) {
    const api = coreApi();
    if (api.saveAuth) {
      api.saveAuth(token, user);
      return;
    }
    localStorage.removeItem(TOKEN_KEY);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  async function loadLoginConfig() {
    const hint = $('loginConfigHint');
    try {
      const api = coreApi();
      if (!api.apiJson) {
        return;
      }
      const data = await api.apiJson('/auth/login-config');
      if (!hint || data.status !== 'ok') {
        return;
      }
      hint.textContent = '請輸入管理員提供的帳號及密碼；首次登入會引導設定個人密碼。';
      if (!data.initial_password_configured) {
        hint.textContent = '尚未設定初始密碼，請先執行 scripts/bootstrap_env.py 再登入。';
      }
    } catch (_) {
      // Login still works without this optional hint.
    }
  }

  async function submitLogin(event) {
    event.preventDefault();
    const username = $('loginUsername')?.value.trim() || '';
    const password = $('loginPassword')?.value || '';
    if (!username || !password) {
      setResult('請輸入使用者 ID 與密碼。');
      return;
    }

    setSubmitting(true);
    setResult('正在驗證帳號密碼...', 'loading');
    try {
      const api = coreApi();
      if (!api.apiJson) {
        throw new Error('Login API 目前無法使用，請重新整理頁面後再試。');
      }
      const data = await api.apiJson('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (data.status !== 'ok') {
        throw new Error(data.message || '登入失敗');
      }
      saveAuth(data.token, data.user);
      setResult('登入成功，正在開啟工作台...', 'success');
      window.location.href = nextPath(data.user);
    } catch (error) {
      setSubmitting(false);
      if (error.code === 'PASSWORD_CHANGE_REQUIRED') {
        $('loginForm').hidden = true;
        $('initialPasswordForm').hidden = false;
        $('initialNewPassword').focus();
        return;
      }
      setResult(authErrorMessage(error));
    }
  }

  function returnToLogin(message = '請重新輸入密碼。') {
    $('loginPassword').value = '';
    $('initialNewPassword').value = '';
    $('initialConfirmPassword').value = '';
    $('initialPasswordResult').textContent = '';
    $('initialPasswordForm').hidden = true;
    $('loginForm').hidden = false;
    setResult(message, 'success');
    $('loginPassword').focus();
  }

  async function submitInitialPassword(event) {
    event.preventDefault();
    const result = $('initialPasswordResult');
    const button = $('initialPasswordSubmit');
    const cancel = $('initialPasswordCancel');
    const newPassword = $('initialNewPassword').value;
    result.className = 'upload-result show error';
    if (newPassword.length < 8) {
      result.textContent = '新密碼至少需要 8 個字元。';
      return;
    }
    if (newPassword !== $('initialConfirmPassword').value) {
      result.textContent = '兩次輸入的新密碼不一致。';
      return;
    }
    button.disabled = true;
    cancel.disabled = true;
    try {
      await coreApi().apiJson('/auth/initial-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: $('loginUsername').value.trim(),
          current_password: $('loginPassword').value,
          new_password: newPassword,
        }),
      });
      returnToLogin('個人密碼已設定，請使用新密碼登入。');
    } catch (error) {
      result.textContent = authErrorMessage(error, true);
    } finally {
      button.disabled = false;
      cancel.disabled = false;
    }
  }

  function bindQuickAccounts() {
    document.querySelectorAll('[data-user]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = $('loginUsername');
        const password = $('loginPassword');
        if (username) {
          username.value = button.dataset.user || '';
        }
        setResult(`已帶入使用者 ID：${button.dataset.user || ''}。請輸入帳號密碼繼續。`, 'loading');
        password?.focus();
      });
    });
  }

  window.AlarmLogin = { nextPath, safeNextPath };

  document.addEventListener('DOMContentLoaded', () => {
    loadLoginConfig();
    if (new URLSearchParams(window.location.search).get('password_changed') === '1') {
      setResult('密碼已更改，所有裝置已登出。請使用新密碼登入。', 'success');
    }
    $('loginForm')?.addEventListener('submit', submitLogin);
    $('initialPasswordForm')?.addEventListener('submit', submitInitialPassword);
    $('initialPasswordCancel')?.addEventListener('click', () => returnToLogin());
  });
})();
