import os
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api_schemas import (
    API_ERROR_RESPONSES, SystemSettingsEnvelope,
    CompanyDisplayResponse, CompanyPreviewResponse, CompanyApplyResponse,
)
from auth import actor_id, get_actor, is_admin
from repositories.postgres_content import ConcurrentContentUpdateError, PostgresSettingsRepository
from repositories.runtime import postgres_store_enabled
from services.system_settings import DEFAULT_SETTINGS, load_effective_settings, session_hours_override
from services.company_config import CompanyConfig, company_from_settings
from services.json_file_store import write_json_atomic
from services.transactions import json_transactional, postgres_transactional
from storage import DB_PATH


router = APIRouter()
postgres_settings = PostgresSettingsRepository()

DB_DIR = DB_PATH
SETTINGS_FILE = os.path.join(DB_DIR, "system_settings.json")
class UpdateSystemSettings(BaseModel):
    default_manual: Optional[str] = None
    session_hours: Optional[int] = None
    allow_operator_reopen: Optional[bool] = None
    expected_revision: Optional[str] = None


def _load_settings() -> dict:
    return load_effective_settings(
        SETTINGS_FILE,
        postgres_reader=postgres_settings,
        use_postgres=postgres_store_enabled(),
    )


def _save_settings(settings: dict, updated_by: str = "", expected_revision: str | None = None) -> str:
    if postgres_store_enabled():
        return postgres_settings.save_all(settings, updated_by, expected_revision=expected_revision)
    os.makedirs(DB_DIR, exist_ok=True)
    write_json_atomic(SETTINGS_FILE, settings)
    return str(settings.get("revision") or "")


def _settings_response(settings: dict) -> dict:
    response = dict(settings)
    override = session_hours_override(os.getenv("SESSION_TTL_HOURS", ""))
    if override is not None:
        response["session_hours"] = override
        response["session_hours_source"] = "environment"
    else:
        response["session_hours_source"] = "settings"
    return response


@router.get(
    "/system-settings",
    responses={200: {"model": SystemSettingsEnvelope}, **API_ERROR_RESPONSES},
)
async def get_system_settings(actor: dict = Depends(get_actor)):
    if not actor_id(actor):
        return {"status": "error", "message": "Not authenticated"}
    if not is_admin(actor):
        return {"status": "error", "message": "Permission denied"}
    return {"status": "ok", "settings": _settings_response(_load_settings())}


class CompanyImport(BaseModel):
    config: CompanyConfig
    expected_revision: str = ""


@router.get("/company-config", responses={200: {"model": CompanyDisplayResponse}, **API_ERROR_RESPONSES})
async def get_company_config(actor: dict = Depends(get_actor)):
    if not actor_id(actor):
        return {"status": "error", "message": "Not authenticated"}
    from app_context import engines
    from auth import line_allowed

    settings = _load_settings()
    config = company_from_settings(settings)
    lines = [line.model_dump() for line in config.lines if line_allowed(actor, line.id)]
    machines = [machine.model_dump() for machine in config.machines if line_allowed(actor, machine.line_id)]
    return {
        "status": "ok", "company": config.company.model_dump(),
        "default_manual": settings["default_manual"],
        "collections": [
            {"id": item.id, "display_name": item.display_name,
             "ready": bool(engines.get(item.id) and engines[item.id].ready)}
            for item in config.collections
        ],
        "sites": [site.model_dump() for site in config.sites],
        "lines": lines, "machines": machines,
    }


@router.post("/company-config/preview", responses={200: {"model": CompanyPreviewResponse}, **API_ERROR_RESPONSES})
async def preview_company_config(req: CompanyImport, actor: dict = Depends(get_actor)):
    if not actor_id(actor):
        return {"status": "error", "message": "Not authenticated"}
    if not is_admin(actor):
        return {"status": "error", "message": "Permission denied"}
    settings = _load_settings()
    return {
        "status": "ok", "expected_revision": str(settings.get("revision") or ""),
        "before": {"config": company_from_settings(settings).model_dump(),
                   "default_manual": settings["default_manual"],
                   "allow_operator_reopen": settings["allow_operator_reopen"]},
        "after": {"config": req.config.model_dump(), "default_manual": req.config.default_collection,
                  "allow_operator_reopen": req.config.workflow.allow_operator_reopen},
    }


@router.put("/company-config", responses={200: {"model": CompanyApplyResponse}, **API_ERROR_RESPONSES})
@postgres_transactional
@json_transactional(lambda: DB_DIR)
async def apply_company_config(req: CompanyImport, actor: dict = Depends(get_actor)):
    if not actor_id(actor):
        return {"status": "error", "message": "Not authenticated"}
    if not is_admin(actor):
        return {"status": "error", "message": "Permission denied"}
    from datetime import datetime, timezone

    settings = _load_settings()
    if req.expected_revision != str(settings.get("revision") or ""):
        return {"status": "error", "message": "System settings changed since preview. Reload and retry."}
    settings.update(
        company_config=req.config.model_dump(), default_manual=req.config.default_collection,
        allow_operator_reopen=req.config.workflow.allow_operator_reopen,
        updated_by=actor_id(actor), updated_at=datetime.now(timezone.utc).isoformat(),
    )
    if not postgres_store_enabled():
        settings["revision"] = settings["updated_at"]
    try:
        revision = _save_settings(settings, actor_id(actor), expected_revision=req.expected_revision)
    except ConcurrentContentUpdateError as exc:
        return {"status": "error", "message": str(exc)}
    return {"status": "ok", "revision": revision}


@router.patch(
    "/system-settings",
    responses={200: {"model": SystemSettingsEnvelope}, **API_ERROR_RESPONSES},
)
@postgres_transactional
@json_transactional(lambda: DB_DIR)
async def update_system_settings(req: UpdateSystemSettings, actor: dict = Depends(get_actor)):
    if not actor_id(actor):
        return {"status": "error", "message": "Not authenticated"}
    if not is_admin(actor):
        return {"status": "error", "message": "Permission denied"}
    if req.session_hours is not None and session_hours_override(os.getenv("SESSION_TTL_HOURS", "")) is not None:
        return {
            "status": "error",
            "message": "session_hours is controlled by SESSION_TTL_HOURS and cannot be changed here",
        }

    from datetime import datetime

    settings = _load_settings()
    current_revision = str(settings.get("revision") or "")
    changed = any(
        value is not None
        for value in (req.default_manual, req.session_hours, req.allow_operator_reopen)
    )
    if changed and current_revision and req.expected_revision != current_revision:
        return {"status": "error", "message": "System settings changed since you loaded them. Reload and retry."}
    manuals = {item.id for item in company_from_settings(settings).collections}
    if req.default_manual is not None and req.default_manual not in manuals:
        return {"status": "error", "message": "Invalid default_manual"}
    if req.default_manual in manuals:
        settings["default_manual"] = req.default_manual
    if req.session_hours is not None:
        settings["session_hours"] = min(max(req.session_hours, 1), 72)
    if req.allow_operator_reopen is not None:
        settings["allow_operator_reopen"] = req.allow_operator_reopen
    updated_at = datetime.now().isoformat()
    settings["updated_by"] = actor_id(actor)
    settings["updated_at"] = updated_at
    if not postgres_store_enabled():
        settings["revision"] = updated_at
    try:
        revision = _save_settings(settings, actor_id(actor), expected_revision=req.expected_revision)
    except ConcurrentContentUpdateError as exc:
        return {"status": "error", "message": str(exc)}
    settings["revision"] = revision
    return {"status": "ok", "settings": _settings_response(settings)}
