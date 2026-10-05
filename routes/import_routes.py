"""PostgreSQL standard-deployment account import and administrator batch history."""
from __future__ import annotations

import hashlib
import hmac
from io import BytesIO
from pathlib import PureWindowsPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, text

import auth
from api_schemas import (API_ERROR_RESPONSES, ApiErrorResponse, UserImportPreviewResponse,
                         UserImportResponse, ImportBatchListResponse, ImportBatchDetailResponse)
from db.models import User
from db.session import transaction_scope
from repositories.postgres_auth import apply_user_payload
from repositories.runtime import postgres_store_enabled
from services.company_config import runtime_settings
from services import import_batches, user_import

router = APIRouter()


def admission(actor):
    if not auth.actor_id(actor):
        return {'status': 'error', 'message': 'Not authenticated'}
    if not auth.is_admin(actor):
        return {'status': 'error', 'message': 'Permission denied'}
    if not postgres_store_enabled():
        return {'status': 'error', 'message': 'Batch users and import history require the PostgreSQL SOP deployment'}
    return None


@router.get('/users/import-template', responses={200: {'model': ApiErrorResponse, 'content': {
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': {'schema': {'type': 'string', 'format': 'binary'}}}},
    **API_ERROR_RESPONSES})
async def user_template(actor: dict = Depends(auth.get_actor)):
    denied = admission(actor)
    if denied:
        return denied
    from openpyxl import Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'users'
    sheet.append(user_import.FIELDS)
    # Account IDs and passwords are text, including numeric-looking values.
    for row in sheet.iter_rows(min_row=2, max_row=201, max_col=6):
        for cell in row:
            cell.number_format = '@'
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename="users-template.xlsx"'})


def confirm_users(rows, content, actor_id, preview_token, filename):
    with transaction_scope() as session:
        if session.get_bind().dialect.name == 'postgresql':
            session.execute(text('SELECT pg_advisory_xact_lock(684720260921)'))
            session.execute(text('SELECT pg_advisory_xact_lock(684720260924)'))
        session.scalars(select(User).order_by(User.user_id).with_for_update()).all()
        accounts = auth.load_users()
        current_actor = accounts.get(actor_id, {})
        if not current_actor.get('active') or current_actor.get('role') != 'admin':
            raise ValueError('Permission denied: administrator account changed')
        settings = runtime_settings()
        expected = user_import.token(content, actor_id, accounts, settings)
        if not hmac.compare_digest(expected, preview_token):
            raise ValueError('File, accounts or company settings changed since preview; preview again')
        previews, accepted = user_import.prepare(rows, accounts, settings)
        if not accepted:
            raise ValueError('No valid accounts to import')
        for item in accepted:
            req = item['request']
            payload = auth.build_user(req, req.user_id, req.password)
            payload['must_change_password'] = True
            user = User(user_id=req.user_id)
            apply_user_payload(user, req.user_id, payload)
            session.add(user)  # INSERT only: never overwrite an existing account.
        session.flush()
        valid_ids = {item['row']: item['request'].user_id for item in accepted}
        for row in previews:
            row['record_id'] = valid_ids.get(row['row'], '')
        batch = import_batches.record_batch(kind='users', filename=filename, digest=hashlib.sha256(content).hexdigest(),
            actor=actor_id, rows=previews, imported=len(accepted), skipped=len(previews)-len(accepted))
        return {'status': 'ok', 'batch_id': batch['batch_id'], 'filename': filename,
                'imported': batch['imported'], 'skipped': batch['skipped'], 'candidate_count': 0}


async def handle_users(file, actor, *, preview_only=False, preview_token=None):
    denied = admission(actor)
    if denied:
        return denied
    filename = PureWindowsPath(file.filename or '').name[:255]
    if not filename.lower().endswith('.xlsx'):
        return {'status': 'error', 'message': 'Only .xlsx files are supported'}
    content = await file.read(user_import.MAX_BYTES + 1)
    try:
        rows = await run_in_threadpool(user_import.read_rows, content)
        if preview_only:
            accounts, settings = auth.load_users(), runtime_settings()
            previews, accepted = user_import.prepare(rows, accounts, settings)
            return {'status': 'ok', 'filename': filename, 'valid': len(accepted),
                    'skipped': len(previews)-len(accepted), 'rows': previews, 'candidate_count': 0,
                    'preview_token': user_import.token(content, auth.actor_id(actor), accounts, settings)}
        if not preview_token:
            raise ValueError('Preview the user file before confirming import')
        return await run_in_threadpool(confirm_users, rows, content, auth.actor_id(actor), preview_token, filename)
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Unable to import accounts; no accounts were created'
        # Only confirmed attempts enter history; the uploaded content is never persisted.
        if not preview_only and preview_token:
            try:
                with transaction_scope():
                    import_batches.record_batch(kind='users', filename=filename, digest=hashlib.sha256(content).hexdigest(),
                        actor=auth.actor_id(actor), rows=[], imported=0, skipped=0, status='failed', error=message)
            except Exception:
                message += '; history could not be saved'
        return {'status': 'error', 'message': message}


@router.post('/users/import-excel/preview', responses={200: {'model': UserImportPreviewResponse}, **API_ERROR_RESPONSES})
async def preview_users(file: UploadFile = File(...), actor: dict = Depends(auth.get_actor)):
    return await handle_users(file, actor, preview_only=True)


@router.post('/users/import-excel', responses={200: {'model': UserImportResponse}, **API_ERROR_RESPONSES})
async def import_users(file: UploadFile = File(...), actor: dict = Depends(auth.get_actor),
                       preview_token: Annotated[str | None, Form(max_length=64)] = None):
    return await handle_users(file, actor, preview_token=preview_token)


@router.get('/imports/batches', responses={200: {'model': ImportBatchListResponse}, **API_ERROR_RESPONSES})
async def batch_history(actor: dict = Depends(auth.get_actor), limit: int = Query(20, ge=1, le=100),
                        offset: int = Query(0, ge=0), kind: str = Query('', pattern='^(users|work_orders)?$')):
    denied = admission(actor)
    if denied:
        return denied
    return {'status': 'ok', **import_batches.list_batches(limit=limit, offset=offset, kind=kind)}


@router.get('/imports/batches/{batch_id}', responses={200: {'model': ImportBatchDetailResponse}, **API_ERROR_RESPONSES})
async def batch_detail(batch_id: str, actor: dict = Depends(auth.get_actor)):
    denied = admission(actor)
    if denied:
        return denied
    batch = import_batches.get_batch(batch_id)
    return {'status': 'ok', 'batch': batch} if batch else {'status': 'error', 'message': 'Import batch not found'}
