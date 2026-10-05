"""Password transitions use real local users, hashes and cookie sessions."""
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import auth


@pytest.fixture
def password_app(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, 'postgres_store_enabled', lambda: False)
    monkeypatch.setattr(auth, 'USER_FILE', str(tmp_path / 'users.json'))
    monkeypatch.setattr(auth, 'SESSION_FILE', str(tmp_path / 'sessions.json'))
    monkeypatch.setattr(auth, 'DB_DIR', str(tmp_path))
    for state in (auth._login_failures, auth._login_lockouts, auth._login_last_seen):
        state.clear()
    users = {}
    for role in ('admin', 'operator', 'maintenance', 'supervisor'):
        user = auth.build_user(auth.CreateUserRequest(user_id=role, role=role), role, 'OriginalStrong!29')
        user['must_change_password'] = False
        users[role] = user
    auth.save_users(users)
    app = FastAPI()
    app.include_router(auth.router)
    return app


def login(client, user, password='OriginalStrong!29'):
    return client.post('/auth/login', json={'username': user, 'password': password})


@pytest.mark.parametrize('role', ('admin', 'operator', 'maintenance', 'supervisor'))
def test_self_change_revokes_all_sessions_and_preserves_other_accounts(password_app, role):
    with TestClient(password_app) as first, TestClient(password_app) as second, TestClient(password_app) as other:
        token = login(first, role).json()['token']
        assert login(second, role).status_code == 200
        peer = 'operator' if role == 'admin' else 'admin'
        assert login(other, peer).status_code == 200
        before = auth.load_users()[role]
        response = first.post('/auth/change-password', json={
            'current_password': 'OriginalStrong!29', 'new_password': 'PersonalDistinct!30'})
        assert response.status_code == 200
        assert 'Max-Age=0' in response.headers['set-cookie']
        assert first.get('/auth/me').status_code == 401
        assert second.get('/auth/me').status_code == 401
        assert second.get('/auth/me', headers={'Authorization': 'Bearer '+token}).status_code == 401
        assert other.get('/auth/me').status_code == 200
        assert login(first, role).status_code == 401
        assert login(first, role, 'PersonalDistinct!30').status_code == 200
        after = auth.load_users()[role]
        assert after['credential_epoch'] == before['credential_epoch'] + 1
        assert after['role'] == before['role']
        assert after['must_change_password'] is False


def test_change_requires_login_current_password_and_rejects_target_override(password_app):
    with TestClient(password_app) as client:
        body = {'current_password': 'OriginalStrong!29', 'new_password': 'PersonalDistinct!30'}
        assert client.post('/auth/change-password', json=body).status_code == 401
        assert login(client, 'operator').status_code == 200
        before = auth.load_users()
        assert client.post('/auth/change-password', json={**body, 'user_id': 'admin'}).status_code == 422
        for update in ({'current_password': 'WrongPassword!'}, {'new_password': 'OriginalStrong!29'},
                       {'new_password': 'password1'}):
            assert client.post('/auth/change-password', json={**body, **update}).status_code == 400
        assert auth.load_users() == before
        assert client.get('/auth/me').status_code == 200


def test_wrong_current_password_is_throttled(password_app, monkeypatch):
    monkeypatch.setattr(auth, 'LOGIN_FAILURE_LIMIT', 2)
    with TestClient(password_app) as client:
        assert login(client, 'operator').status_code == 200
        body = {'current_password': 'WrongPassword!', 'new_password': 'PersonalDistinct!30'}
        assert client.post('/auth/change-password', json=body).status_code == 400
        assert client.post('/auth/change-password', json=body).status_code == 429
        blocked = client.post('/auth/change-password', json={**body, 'current_password': 'OriginalStrong!29'})
        assert blocked.status_code == 429 and int(blocked.headers['retry-after']) > 0
        assert client.get('/auth/me').status_code == 200


def test_concurrent_change_does_not_overwrite_or_revoke(password_app):
    with TestClient(password_app) as client:
        assert login(client, 'operator').status_code == 200
        before = auth.load_users()
        with patch.object(auth, 'save_user', side_effect=auth.ConcurrentUserUpdateError):
            response = client.post('/auth/change-password', json={
                'current_password': 'OriginalStrong!29', 'new_password': 'PersonalDistinct!30'})
        assert response.status_code == 409
        assert auth.load_users() == before
        assert client.get('/auth/me').status_code == 200


def test_admin_issues_temporary_password_and_owner_sets_final_password(password_app):
    with TestClient(password_app) as admin, TestClient(password_app) as owner:
        assert login(admin, 'admin').status_code == 200
        assert login(owner, 'operator').status_code == 200
        reset = admin.patch('/users/operator/password', json={
            'password': 'TemporaryOnly!29', 'expected_updated_at': auth.load_users()['operator']['updated_at']})
        assert reset.status_code == 200 and reset.json()['user']['must_change_password'] is True
        assert owner.get('/auth/me').status_code == 401
        assert login(owner, 'operator').status_code == 401
        initial = login(owner, 'operator', 'TemporaryOnly!29')
        assert initial.status_code == 403 and initial.json()['error_code'] == 'PASSWORD_CHANGE_REQUIRED'
        assert owner.get('/auth/me').status_code == 401
        changed = owner.post('/auth/initial-password', json={
            'username': 'operator', 'current_password': 'TemporaryOnly!29', 'new_password': 'OwnerPrivate!30'})
        assert changed.status_code == 200
        assert login(owner, 'operator', 'TemporaryOnly!29').status_code == 401
        assert login(owner, 'operator', 'OwnerPrivate!30').status_code == 200
        denied = owner.patch('/users/admin/password', json={'password': 'Unauthorized!29'})
        assert denied.json()['status'] == 'error'
        own_reset = admin.patch('/users/admin/password', json={'password': 'BypassCurrent!29'})
        assert own_reset.json()['status'] == 'error'


def test_individually_created_account_requires_initial_change(password_app):
    with TestClient(password_app) as admin, TestClient(password_app) as owner:
        assert login(admin, 'admin').status_code == 200
        created = admin.post('/users', json={'user_id': 'newperson', 'role': 'operator', 'password': 'TemporaryOnly!29'})
        assert created.json()['user']['must_change_password'] is True
        assert login(owner, 'newperson', 'TemporaryOnly!29').status_code == 403
        assert owner.post('/auth/initial-password', json={
            'username': 'newperson', 'current_password': 'TemporaryOnly!29', 'new_password': 'OwnerPrivate!30'}).status_code == 200
        assert login(owner, 'newperson', 'OwnerPrivate!30').status_code == 200
