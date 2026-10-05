import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from services.company_config import CompanyConfig, resolve_manual
from services.system_settings import load_effective_settings
from routes import settings_routes

ROOT = Path(__file__).resolve().parents[2]
ADMIN = {"user_id": "admin01", "role": "admin", "line_scope": ["*"]}
OPERATOR = {"user_id": "operator01", "role": "operator", "line_scope": ["utilities"]}


def example(name="compressor"):
    return json.loads((ROOT / "templates" / f"company.{name}-demo.json").read_text(encoding="utf-8"))


class CompanyValidationTests(unittest.TestCase):
    def test_both_examples_and_resolution(self):
        for name in ("cnc", "compressor"):
            config = CompanyConfig.model_validate(example(name))
            settings = {"company_config": config.model_dump(), "default_manual": config.default_collection}
            machine = config.machines[0]
            self.assertEqual((config.default_collection, ""), resolve_manual(settings=settings))
            self.assertEqual((machine.collection, machine.line_id), resolve_manual(machine_id=machine.id, settings=settings))

    def test_invalid_references_and_modules(self):
        changes = [
            lambda p: p.update(schema_version=2),
            lambda p: p.update(default_collection="missing"),
            lambda p: p["machines"][0].update(line_id="missing"),
            lambda p: p["machines"][0].update(collection="missing"),
            lambda p: p["lines"][0].update(site_id="missing"),
            lambda p: p["collections"][0].update(parser="os.system"),
            lambda p: p["collections"][0].update(id="../bad"),
            lambda p: p["machines"].append(copy.deepcopy(p["machines"][0])),
        ]
        for change in changes:
            payload = example()
            change(payload)
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                CompanyConfig.model_validate(payload)

    def test_unknown_machine_collection_and_mapping_conflicts_fail(self):
        settings = {"company_config": example(), "default_manual": "compressor_demo"}
        for arguments in ({"machine_id": "unknown"}, {"manual": "808d"},
                          {"machine_id": "AIR-01", "manual": "808d"},
                          {"machine_id": "AIR-01", "line_id": "wrong"}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                resolve_manual(**arguments, settings=settings)


class CompanyRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "system_settings.json"
        self.patches = [
            patch.object(settings_routes, "DB_DIR", self.tmp.name),
            patch.object(settings_routes, "SETTINGS_FILE", str(self.path)),
            patch.dict(os.environ, {"DATA_STORE": "json", "SESSION_TTL_HOURS": ""}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    async def test_preview_is_read_only_apply_is_revision_checked_and_persistent(self):
        request = settings_routes.CompanyImport(config=example())
        preview = await settings_routes.preview_company_config(request, actor=ADMIN)
        self.assertFalse(self.path.exists())
        self.assertEqual("compressor_demo", preview["after"]["default_manual"])
        applied = await settings_routes.apply_company_config(request, actor=ADMIN)
        self.assertEqual("ok", applied["status"])
        self.assertEqual("compressor_demo", load_effective_settings(self.path)["default_manual"])
        stale = await settings_routes.apply_company_config(request, actor=ADMIN)
        self.assertEqual("error", stale["status"])
        self.assertIn("changed since", stale["message"])

    async def test_role_filtered_display_does_not_expose_management_settings(self):
        await settings_routes.apply_company_config(settings_routes.CompanyImport(config=example()), actor=ADMIN)
        display = await settings_routes.get_company_config(actor=OPERATOR)
        self.assertEqual("AIR-01", display["machines"][0]["id"])
        self.assertFalse(display["collections"][0]["ready"])
        self.assertNotIn("session_hours", display)
        self.assertNotIn("allow_operator_reopen", display)
        self.assertNotIn("parser", display["collections"][0])
        other = await settings_routes.get_company_config(actor={**OPERATOR, "line_scope": ["elsewhere"]})
        self.assertEqual([], other["machines"])
        self.assertEqual([], other["lines"])
        denied = await settings_routes.apply_company_config(settings_routes.CompanyImport(config=example()), actor=OPERATOR)
        self.assertEqual("Permission denied", denied["message"])
        self.assertEqual("Not authenticated", (await settings_routes.get_company_config(actor={}))['message'])

    async def test_admin_default_persists_across_load_and_only_accepts_company_ids(self):
        payload = example()
        payload["collections"].append({**payload["collections"][0], "id": "sop_two"})
        applied = await settings_routes.apply_company_config(settings_routes.CompanyImport(config=payload), actor=ADMIN)
        saved = await settings_routes.update_system_settings(settings_routes.UpdateSystemSettings(
            default_manual="sop_two", expected_revision=applied["revision"],
        ), actor=ADMIN)
        self.assertEqual("ok", saved["status"])
        self.assertEqual("sop_two", load_effective_settings(self.path)["default_manual"])
        denied = await settings_routes.update_system_settings(settings_routes.UpdateSystemSettings(
            default_manual="808d", expected_revision=saved["settings"]["revision"],
        ), actor=ADMIN)
        self.assertEqual("Invalid default_manual", denied["message"])

    async def test_machine_mapping_is_used_by_alarm_and_issue_endpoints(self):
        from app_context import AlarmTrigger
        from routes import alarm_routes
        import issues

        settings = {"company_config": example(), "default_manual": "compressor_demo"}
        with patch("services.company_config.runtime_settings", return_value=settings):
            for actor in (ADMIN, OPERATOR):
                result = await alarm_routes.trigger_alarm(
                    AlarmTrigger(alarm_code="AIR-01", machine_id="AIR-01", manual="808d"),
                    actor=actor, trigger_token=None,
                )
                self.assertIn("conflicts", result["message"])
            with patch.object(issues, "create_issue_dict", side_effect=lambda **kw: {"issue_id": "test", **kw}):
                created = await issues.api_create_issue(
                    issues.CreateIssue(machine_id="AIR-01", description="模擬異常"), actor=OPERATOR,
                )
                self.assertEqual("compressor_demo", created["issue"]["manual"])
                self.assertEqual("utilities", created["issue"]["line_id"])
            denied = await issues.api_create_issue(
                issues.CreateIssue(machine_id="AIR-01", description="模擬異常"),
                actor={**OPERATOR, "line_scope": ["wrong"]},
            )
            self.assertEqual("Permission denied", denied["message"])

    async def test_query_and_ingest_reject_unregistered_collections(self):
        from routes import chat_lookup_routes, ingest_routes
        settings = {"company_config": example(), "default_manual": "compressor_demo"}
        with patch("services.company_config.runtime_settings", return_value=settings):
            result = await chat_lookup_routes.lookup_alarm("808d", code="3000", actor=ADMIN)
            self.assertEqual("Unknown collection: 808d", result["message"])
            with self.assertRaisesRegex(ValueError, "Unknown collection"):
                ingest_routes.validate_collection_name("808d")
            self.assertEqual("compressor_demo", ingest_routes.validate_collection_name("compressor_demo"))
