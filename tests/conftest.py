"""Explicit shared fixtures; individual tests choose when to use them."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def compressor_order_store(tmp_path, monkeypatch):
    import work_orders

    monkeypatch.setenv("DATA_STORE", "json")
    monkeypatch.setattr(work_orders, "DB_DIR", str(tmp_path))
    monkeypatch.setattr(work_orders, "WO_FILE", str(tmp_path / "work_orders.json"))
    monkeypatch.setattr(work_orders, "ARCHIVE_DIR", str(tmp_path / "archive"))
    root = Path(__file__).resolve().parents[1]
    settings = {
        "company_config": json.loads((root / "templates/company.compressor-demo.json").read_text(encoding="utf-8")),
        "default_manual": "compressor_demo", "revision": "initial",
    }
    monkeypatch.setattr(work_orders, "runtime_settings", lambda: settings)
    return settings
