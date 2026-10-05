import asyncio
from io import BytesIO
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import auth
from api_contracts import ApiContractMiddleware
from db.base import Base
from db.models import ImportBatch, User
from db import session as database
from repositories.postgres_auth import PostgresUserRepository
from routes import import_routes
from services import import_batches, user_import
from tests.support.uploads import ADMIN, workbook_bytes

PASSWORD = 'Batch-Initial-Secret-9357'
HEADER = ['user_id', 'name', 'role', 'team', 'line_scope', 'password']


@pytest.fixture
def batch_store(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'batch.db'), connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    monkeypatch.setenv('DATA_STORE', 'postgresql')
    monkeypatch.setattr(database, '_session_factory', sessionmaker(engine, expire_on_commit=False, autoflush=False))
    monkeypatch.setattr(auth, 'DB_DIR', str(tmp_path))
    monkeypatch.setattr(auth, 'USER_FILE', str(tmp_path / 'users.json'))
    PostgresUserRepository().save_one('admin01', {'user_id': 'admin01', 'role': 'admin', 'name': 'Admin',
        'active': True, 'line_scope': ['*'], 'password_hash': 'test-hash'})
    company = json.loads((Path(__file__).resolve().parents[2] / 'templates/company.compressor-demo.json').read_text(encoding='utf-8'))
    settings = {'company_config': company, 'default_manual': 'compressor_demo', 'revision': 'one'}
    monkeypatch.setattr(import_routes, 'runtime_settings', lambda: settings)
    yield settings
    engine.dispose()


def call(content, *, preview=True, token=None, actor=ADMIN):
    return asyncio.run(import_routes.handle_users(UploadFile(filename='staff.xlsx', file=BytesIO(content)), actor,
        preview_only=preview, preview_token=token))


def valid_file():
    return workbook_bytes([HEADER, ['staff01', 'Name', 'maintenance', 'day', 'utilities', PASSWORD]])


def test_preview_redacts_password_and_reports_every_invalid_row_without_writes(batch_store):
    content = workbook_bytes([HEADER,
        ['staff01', 'Name', 'maintenance', 'day', 'utilities', PASSWORD],
        ['staff01', 'Repeated', 'operator', '', 'utilities', PASSWORD],
        ['admin01', 'Existing', 'admin', '', '*', PASSWORD],
        ['badrole', '', 'owner', '', 'utilities', PASSWORD],
        ['missingrole', '', '', '', 'utilities', PASSWORD],
        ['badline', '', 'operator', '', 'wrong-line', PASSWORD],
        ['weak', '', 'operator', '', 'utilities', 'password'],
    ])
    result = call(content)
    assert result['status'] == 'ok' and result['valid'] == 1 and result['skipped'] == 6
    assert PASSWORD not in json.dumps(result) and 'password' not in result['rows'][0]['values']
    assert set(auth.load_users()) == {'admin01'}
    assert import_batches.list_batches()['total'] == 0


def test_confirm_is_atomic_insert_only_with_redacted_durable_history(batch_store):
    password = ' ' + PASSWORD + ' '
    content = workbook_bytes([HEADER, ['staff01', 'Name', 'maintenance', '', 'utilities', password],
                             ['invalid', '', 'owner', '', 'utilities', PASSWORD]])
    preview = call(content)
    result = call(content, preview=False, token=preview['preview_token'])
    assert result['status'] == 'ok' and result['imported'] == 1 and result['skipped'] == 1
    user = auth.load_users()['staff01']
    assert user['must_change_password'] is True
    assert auth.verify_password(password, user['password_hash'])
    assert not auth.verify_password(PASSWORD, user['password_hash'])
    batch = import_batches.get_batch(result['batch_id'])
    assert batch['rows'][0]['record_id'] == 'staff01'
    assert batch['rows'][1]['error']
    assert PASSWORD not in json.dumps(batch) and 'password_hash' not in json.dumps(batch)
    repeated = call(content, preview=False, token=preview['preview_token'])
    assert repeated['status'] == 'error'
    assert auth.load_users()['staff01'] == user
    assert import_batches.list_batches()['total'] == 2  # One success and one rejected confirmation.
    assert call(content)['valid'] == 0


@pytest.mark.parametrize('changed', ['file', 'settings', 'account', 'actor'])
def test_stale_preview_rejected_and_recorded_without_accounts(batch_store, changed):
    content = valid_file()
    token = call(content)['preview_token']
    actor = ADMIN
    if changed == 'file':
        content = workbook_bytes([HEADER, ['other', '', 'operator', '', 'utilities', PASSWORD]])
    elif changed == 'settings':
        batch_store['revision'] = 'two'
    elif changed == 'account':
        PostgresUserRepository().save_one('admin01', {**auth.load_users()['admin01'], 'team': 'changed'})
    else:
        actor = {**ADMIN, 'user_id': 'another-admin'}
    result = call(content, preview=False, token=token, actor=actor)
    assert result['status'] == 'error'
    assert set(auth.load_users()) == {'admin01'}
    assert import_batches.list_batches()['batches'][0]['status'] == 'failed'


def test_history_failure_rolls_back_accounts(batch_store, monkeypatch):
    content = valid_file()
    token = call(content)['preview_token']
    monkeypatch.setattr(import_batches, 'record_batch', lambda **kwargs: (_ for _ in ()).throw(OSError('disk full')))
    result = call(content, preview=False, token=token)
    assert result['status'] == 'error'
    assert set(auth.load_users()) == {'admin01'}
    with database.session_scope() as session:
        assert list(session.scalars(select(ImportBatch))) == []


def test_work_order_and_history_commit_together(batch_store, tmp_path, monkeypatch):
    import work_orders
    from tests.support.uploads import Upload
    monkeypatch.setattr(work_orders, 'DB_DIR', str(tmp_path))
    monkeypatch.setattr(work_orders, 'runtime_settings', lambda: batch_store)
    content = workbook_bytes([['alarm_code', 'machine_id'], ['AIR-A', 'AIR-01']])
    preview = asyncio.run(work_orders.preview_excel(Upload('work.xlsx', content), actor=ADMIN))
    result = asyncio.run(work_orders.import_excel(Upload('work.xlsx', content), actor=ADMIN, preview_token=preview['preview_token']))
    assert result['status'] == 'ok'
    batch = import_batches.get_batch(result['batch_id'])
    assert batch['kind'] == 'work_orders' and batch['imported'] == 1
    assert batch['rows'][0]['record_id'] == work_orders._load_orders()[0]['id']
    before = work_orders._load_orders()
    other = workbook_bytes([['alarm_code', 'machine_id'], ['AIR-B', 'AIR-01']])
    token = asyncio.run(work_orders.preview_excel(Upload('work.xlsx', other), actor=ADMIN))['preview_token']
    monkeypatch.setattr(import_batches, 'record_batch', lambda **kwargs: (_ for _ in ()).throw(OSError('disk full')))
    result = asyncio.run(work_orders.import_excel(Upload('work.xlsx', other), actor=ADMIN, preview_token=token))
    assert result['status'] == 'error'
    assert work_orders._load_orders() == before


@pytest.mark.parametrize('rows', [
    [['user_id', 'role', 'line_scope', 'password', 'password']],
    [['name'], ['no account header']],
    [HEADER, ['formula', '=1+1', 'operator', '', 'utilities', PASSWORD]],
    [HEADER] + [['u', '', 'operator', '', 'utilities', PASSWORD]] * 201,
])
def test_invalid_shape_formula_and_row_limit_rejected(batch_store, rows):
    assert call(workbook_bytes(rows))['status'] == 'error'
    assert set(auth.load_users()) == {'admin01'}


def test_admin_http_contract_template_and_history_pagination(batch_store):
    app = FastAPI()
    app.add_middleware(ApiContractMiddleware)
    app.include_router(import_routes.router)
    app.dependency_overrides[auth.get_actor] = lambda: ADMIN
    with TestClient(app) as client:
        template = client.get('/users/import-template')
        assert template.status_code == 200
        assert list(user_import.read_rows(template.content)[0]) == HEADER
        content = valid_file()
        files = {'file': ('staff.xlsx', content)}
        preview = client.post('/users/import-excel/preview', files=files).json()
        done = client.post('/users/import-excel', files=files, data={'preview_token': preview['preview_token']}).json()
        history = client.get('/imports/batches?limit=1&offset=0&kind=users').json()
        assert history['total'] == 1 and 'rows' not in history['batches'][0]
        assert client.get('/imports/batches?offset=1').json()['batches'] == []
        assert client.get('/imports/batches/' + done['batch_id']).json()['batch']['rows'][0]['record_id'] == 'staff01'
        for role, code in [('operator', 403), ('maintenance', 403), ('supervisor', 403), ('', 401)]:
            app.dependency_overrides[auth.get_actor] = lambda role=role: {'user_id': 'x' if role else '', 'role': role}
            for path in ('/users/import-template', '/imports/batches', '/imports/batches/' + done['batch_id']):
                assert client.get(path).status_code == code
            for path in ('/users/import-excel', '/users/import-excel/preview'):
                assert client.post(path, files=files).status_code == code
