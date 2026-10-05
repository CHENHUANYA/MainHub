"""Admin import ledger. Successful rows and this record share the caller's transaction."""
from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import func, select
from db.models import ImportBatch
from db.session import session_scope


def record_batch(*, kind: str, filename: str, digest: str, actor: str, rows: list[dict],
                 imported: int, skipped: int, status: str = 'completed', error: str = '') -> dict:
    # Explicit allowlist: never persist spreadsheet values or account credentials.
    safe_rows = [{k: row[k] for k in ('row', 'record_id', 'error', 'warnings') if k in row} for row in rows]
    batch = {'batch_id': uuid.uuid4().hex, 'kind': kind, 'filename': filename[:255],
             'file_sha256': digest, 'actor': actor, 'created_at': datetime.now(timezone.utc).isoformat(),
             'status': status, 'imported': imported, 'skipped': skipped, 'error': error,
             'rows': safe_rows}
    with session_scope() as session:
        session.add(ImportBatch(batch_id=batch['batch_id'], kind=kind, payload=batch))
        session.flush()
    return batch


def list_batches(*, limit: int = 20, offset: int = 0, kind: str = '') -> dict:
    with session_scope() as session:
        query = select(ImportBatch)
        count = select(func.count()).select_from(ImportBatch)
        if kind:
            query = query.where(ImportBatch.kind == kind)
            count = count.where(ImportBatch.kind == kind)
        records = session.scalars(query.order_by(ImportBatch.created_at.desc(), ImportBatch.batch_id.desc())
                                  .offset(offset).limit(limit)).all()
        return {'batches': [{k: v for k, v in row.payload.items() if k != 'rows'} for row in records],
                'total': session.scalar(count), 'limit': limit, 'offset': offset}


def get_batch(batch_id: str) -> dict | None:
    with session_scope() as session:
        row = session.get(ImportBatch, batch_id)
        return dict(row.payload) if row else None
