"""Validated company catalog, stored alongside the existing system settings."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NamedEntry(ConfigModel):
    id: Identifier
    display_name: str = Field(min_length=1, max_length=128)


class Collection(NamedEntry):
    domain: str = Field(default="maintenance", min_length=1, max_length=64)
    # Controlled runtime names; configuration never imports arbitrary code.
    parser: Literal["sinumerik_alarm_v1", "text_v1"] = "sinumerik_alarm_v1"
    prompt_profile: Literal["cnc_maintenance_v1", "maintenance_v1"] = "cnc_maintenance_v1"


class Line(NamedEntry):
    site_id: Identifier | None = None


class Machine(NamedEntry):
    line_id: Identifier
    model: str = Field(default="", max_length=128)
    collection: Identifier


class Workflow(ConfigModel):
    allow_operator_reopen: bool = False


class CompanyConfig(ConfigModel):
    schema_version: Literal[1]
    company: NamedEntry
    default_collection: Identifier
    collections: list[Collection] = Field(min_length=1, max_length=200)
    sites: list[NamedEntry] = Field(default_factory=list, max_length=200)
    lines: list[Line] = Field(default_factory=list, max_length=2000)
    machines: list[Machine] = Field(default_factory=list, max_length=10000)
    workflow: Workflow = Field(default_factory=Workflow)

    @model_validator(mode="after")
    def validate_references(self) -> CompanyConfig:
        for name in ("collections", "sites", "lines", "machines"):
            ids = [entry.id for entry in getattr(self, name)]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name}: duplicate ID")
        collections = {entry.id for entry in self.collections}
        lines = {entry.id for entry in self.lines}
        sites = {entry.id for entry in self.sites}
        if self.default_collection not in collections:
            raise ValueError("default_collection: unknown collection")
        for line in self.lines:
            if line.site_id and line.site_id not in sites:
                raise ValueError(f"lines.{line.id}.site_id: unknown site {line.site_id}")
        for machine in self.machines:
            if machine.line_id not in lines:
                raise ValueError(f"machines.{machine.id}.line_id: unknown line {machine.line_id}")
            if machine.collection not in collections:
                raise ValueError(f"machines.{machine.id}.collection: unknown collection {machine.collection}")
        return self


def legacy_config() -> CompanyConfig:
    path = Path(__file__).resolve().parents[1] / "templates" / "company.legacy.json"
    return CompanyConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))


def company_from_settings(settings: dict) -> CompanyConfig:
    payload = settings.get("company_config")
    return CompanyConfig.model_validate(payload) if payload is not None else legacy_config()


def runtime_settings() -> dict:
    # Lazy imports avoid the storage/auth/settings initialization cycle.
    from repositories.postgres_content import PostgresSettingsRepository
    from services.system_settings import load_effective_settings
    from storage import DB_PATH

    return load_effective_settings(
        Path(DB_PATH) / "system_settings.json", postgres_reader=PostgresSettingsRepository()
    )


def default_manual() -> str:
    settings = runtime_settings()
    return str(settings["default_manual"])


def collection_config(collection: str | None = None, *, settings: dict | None = None) -> Collection:
    settings = runtime_settings() if settings is None else settings
    config = company_from_settings(settings)
    selected = collection or str(settings.get("default_manual") or config.default_collection)
    match = next((item for item in config.collections if item.id == selected), None)
    if match is not None:
        return match
    if settings.get("company_config") is not None:
        raise ValueError(f"Unknown collection: {selected}")
    # Existing deployments can retain unregistered legacy collections.
    return Collection(id=selected, display_name=selected)


def validate_registered_collection(collection: str) -> None:
    settings = runtime_settings()
    if settings.get("company_config") is not None:
        config = company_from_settings(settings)
        if collection not in {item.id for item in config.collections}:
            raise ValueError(f"Unknown collection: {collection}")


def resolve_manual(manual: str | None = None, machine_id: str | None = None,
                   line_id: str | None = None, *, settings: dict | None = None) -> tuple[str, str]:
    """Resolve new records only; never rewrite historic collection identifiers."""
    settings = runtime_settings() if settings is None else settings
    config = company_from_settings(settings)
    explicit = (manual or "").strip()
    machine_id = (machine_id or "").strip()
    line = (line_id or "").strip()
    strict = settings.get("company_config") is not None
    machine = next((item for item in config.machines if item.id == machine_id), None)
    if strict and machine_id and machine is None:
        raise ValueError(f"Unknown machine: {machine_id}; configure its collection mapping first")
    if machine:
        if explicit and explicit != machine.collection:
            raise ValueError(f"Manual conflicts with machine {machine_id}: expected {machine.collection}")
        if line and line != machine.line_id:
            raise ValueError(f"Line conflicts with machine {machine_id}: expected {machine.line_id}")
        line = machine.line_id
    if strict and line and line not in {item.id for item in config.lines}:
        raise ValueError(f"Unknown line: {line}")
    selected = explicit or (machine.collection if machine else str(settings.get("default_manual") or config.default_collection))
    if strict and selected not in {item.id for item in config.collections}:
        raise ValueError(f"Unknown collection: {selected}")
    # Existing deployments may have extra catalogs, but never permit unsafe IDs.
    import re
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", selected):
        raise ValueError("Invalid manual name")
    return selected, line
