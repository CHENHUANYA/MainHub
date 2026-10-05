from __future__ import annotations

import zipfile
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any, Callable, Iterable, Mapping, Sequence
from services.company_config import resolve_manual


@dataclass(frozen=True)
class XlsxArchiveLimits:
    max_entries: int
    max_uncompressed_bytes: int
    max_shared_strings_bytes: int
    max_compression_ratio: float


@dataclass(frozen=True)
class ImportSummary:
    imported: int
    skipped: int
    errors: list[str]
    candidate_count: int
    rows: list[dict] = field(default_factory=list)
    batch_id: str = ''


IMPORT_FIELDS = (
    "alarm_code", "machine_id", "manual", "priority", "status", "assigned_to",
    "description", "resolution", "notes", "root_cause", "repair_action", "source",
)


def import_key(values: Mapping[str, str], source_record_id: str = "") -> str:
    # A stable source ID distinguishes separate incidents with identical text.
    # Without one, deduplicate the normalized imported content, never runtime IDs.
    identity = ({"source": values["source"], "source_record_id": source_record_id}
                if source_record_id else dict(values))
    payload = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def detect_columns(header_row: Sequence[Any], field_map: Mapping[str, str]) -> dict[int, str] | None:
    """Map recognized spreadsheet headers to work-order fields."""
    mapping: dict[int, str] = {}
    for index, cell in enumerate(header_row):
        if cell is None:
            continue
        field_name = field_map.get(str(cell).strip())
        if field_name is not None:
            mapping[index] = field_name
    return mapping or None


def validate_xlsx_archive(content: bytes, limits: XlsxArchiveLimits) -> str:
    """Perform bounded ZIP validation before openpyxl expands workbook content."""
    try:
        with zipfile.ZipFile(BytesIO(content), "r") as archive:
            infos = archive.infolist()
            if len(infos) > limits.max_entries:
                return f"XLSX archive has too many entries ({len(infos)} > {limits.max_entries})"

            total_uncompressed = 0
            for info in infos:
                if info.file_size < 0 or info.compress_size < 0:
                    return "Invalid XLSX archive member size"
                total_uncompressed += info.file_size
                if total_uncompressed > limits.max_uncompressed_bytes:
                    max_mb = limits.max_uncompressed_bytes / 1024 / 1024
                    return f"XLSX uncompressed content exceeds {max_mb:g} MB limit"
                if info.filename == "xl/sharedStrings.xml" and info.file_size > limits.max_shared_strings_bytes:
                    max_mb = limits.max_shared_strings_bytes / 1024 / 1024
                    return f"XLSX shared strings exceed {max_mb:g} MB limit"
                if info.compress_size > 0 and info.file_size / info.compress_size > limits.max_compression_ratio:
                    return "XLSX archive compression ratio is too high"

            if "[Content_Types].xml" not in archive.namelist():
                return "Invalid XLSX archive structure"
    except zipfile.BadZipFile:
        return "Invalid XLSX archive"
    return ""


def row_fields(row: Sequence[Any], column_map: Mapping[int, str]) -> dict[str, str]:
    return {
        field_name: str(row[column_index]).strip()
        for column_index, field_name in column_map.items()
        if column_index < len(row) and row[column_index] is not None
    }


def import_workbook_rows(
    rows: Sequence[Sequence[Any]],
    *,
    field_map: Mapping[str, str],
    positional_fields: Sequence[str],
    priorities: Iterable[str],
    statuses: Iterable[str],
    created_by: str,
    build_order: Callable[..., dict],
    closure_error: Callable[[dict], str],
    refresh_knowledge_state: Callable[[dict, list[str]], None],
    append_order_history: Callable[..., None],
    calculate_field_changes: Callable[[dict, dict, list[str]], Any],
    persist_order: Callable[[dict], Any],
    settings: dict | None = None,
    accounts: Mapping[str, dict] | None = None,
    existing_keys: Mapping[str, str] | None = None,
    file_digest: str = "",
    now: Callable[[], datetime] = datetime.now,
) -> ImportSummary:
    """Convert workbook rows into work orders without depending on FastAPI or storage implementations."""
    detected_columns = detect_columns(rows[0], field_map)
    has_header = detected_columns is not None
    column_map = detected_columns or {index: field for index, field in enumerate(positional_fields)}
    data_rows = rows[1:] if has_header else rows
    if len(data_rows) > 1000:
        raise ValueError("Excel import supports at most 1000 data rows")
    valid_priorities = set(priorities)
    valid_statuses = set(statuses)
    imported = 0
    skipped = 0
    errors: list[str] = []
    candidate_count = 0
    preview_rows: list[dict] = []
    seen = dict(existing_keys or {})
    if has_header and ("alarm_code" not in column_map.values() or
                       len(set(column_map.values())) != len(column_map)):
        raise ValueError("Header requires alarm_code and must not contain duplicate fields")

    for row_index, row in enumerate(data_rows, start=2 if has_header else 1):
        if not any(cell is not None and str(cell).strip() for cell in row):
            continue
        preview: dict[str, Any] = {"row": row_index, "values": {}, "warnings": [], "error": ""}
        preview_rows.append(preview)
        try:
            fields = row_fields(row, column_map)
            preview["values"] = fields
            field_limits = {
                "alarm_code": 128,
                "manual": 64,
                "machine_id": 255,
                "priority": 32,
                "status": 32,
                "assigned_to": 128,
                "source": 128,
                "description": 10_000,
                "resolution": 20_000,
                "notes": 10_000,
                "root_cause": 10_000,
                "repair_action": 10_000,
                "verified_by": 128,
                "source_record_id": 255,
            }
            oversized = [name for name, value in fields.items() if len(value) > field_limits.get(name, 10_000)]
            if oversized:
                raise ValueError(f"fields exceed size limits: {', '.join(sorted(oversized))}")
            alarm_code = fields.get("alarm_code", "").strip()
            if not alarm_code:
                raise ValueError("alarm_code is required")

            priority = (fields.get("priority") or "medium").lower()
            if priority not in valid_priorities:
                raise ValueError(f"Unknown priority: {priority}")
            status = (fields.get("status") or "pending").lower()
            if status not in valid_statuses:
                raise ValueError(f"Unknown status: {status}")
            if status == "verified":
                # Imported files are historical input, not proof that the
                # authenticated verifier workflow took place.
                status = "completed"
                preview["warnings"].append("verified becomes completed; authenticated verification is still required")
            if fields.get("verified_by"):
                preview["warnings"].append("verified_by is ignored; spreadsheet values cannot verify a work order")

            manual, _ = resolve_manual(fields.get("manual"), fields.get("machine_id"), settings=settings)
            assignee = fields.get("assigned_to", "")
            if assignee:
                user = (accounts or {}).get(assignee, {})
                if not user.get("user_id"):
                    raise ValueError(f"Unknown assigned_to account: {assignee}; use the account ID")
                if not user.get("active", True):
                    raise ValueError(f"Inactive assigned_to account: {assignee}")
                if user.get("role") != "maintenance":
                    raise ValueError(f"assigned_to must be a maintenance account: {assignee}")
            order = build_order(
                alarm_code=alarm_code,
                manual=manual,
                machine_id=fields.get("machine_id", ""),
                priority=priority,
                description=fields.get("description", ""),
                rag_suggestion="",
                source=fields.get("source") or "excel",
                assigned_to=assignee,
                created_by=created_by,
            )
            knowledge_candidate = False
            before_order = dict(order)
            for field_name in ("resolution", "notes", "root_cause", "repair_action"):
                if fields.get(field_name):
                    order[field_name] = fields[field_name]

            if status != "pending":
                previous_status = order.get("status", "pending")
                order["status"] = status
                changed_fields = ["status", "resolution", "notes", "root_cause", "repair_action"]
                validation_error = closure_error(order)
                if validation_error:
                    raise ValueError(validation_error)
                if status in {"completed", "verified"}:
                    order["completed_at"] = order.get("completed_at") or now().isoformat()
                    order["completed_by"] = created_by
                    changed_fields.append("completed_by")
                elif status == "in_progress":
                    order["accepted_by"] = created_by
                    changed_fields.append("accepted_by")
                refresh_knowledge_state(order, changed_fields)
                knowledge_candidate = order.get("kb_review_status") == "pending_review"
                append_order_history(
                    order,
                    "import_status_override",
                    created_by,
                    changed_fields,
                    previous_status,
                    status,
                    calculate_field_changes(before_order, order, changed_fields),
                )

            preview["values"] = {key: order.get(key, "") for key in IMPORT_FIELDS}
            source_id = fields.get("source_record_id", "")
            key = import_key(preview["values"], source_id)
            if source_id:
                preview["values"]["source_record_id"] = source_id
            if key in seen:
                raise ValueError(f"Duplicate import record: {seen[key]}")
            order["import_key"] = key
            order["import_metadata"] = {
                "version": 1, "file_sha256": file_digest, "row": row_index,
                "source_record_id": source_id, "imported_by": created_by,
            }
            persist_order(order)
            seen[key] = f"row {row_index}"
            if knowledge_candidate:
                candidate_count += 1
            imported += 1
        except Exception as exc:
            preview["values"] = {key: str(value)[:1000] for key, value in preview["values"].items()}
            preview["error"] = str(exc)
            errors.append(f"Row {row_index}: {exc}")
            skipped += 1

    return ImportSummary(
        imported=imported,
        skipped=skipped,
        errors=errors,
        candidate_count=candidate_count,
        rows=preview_rows,
    )
