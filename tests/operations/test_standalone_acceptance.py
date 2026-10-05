import unittest
from argparse import Namespace

from scripts import standalone_acceptance


class StandaloneAcceptanceTests(unittest.TestCase):
    def test_default_steps_use_backup_dry_run(self):
        steps = standalone_acceptance.build_steps(Namespace(
            base_url="http://localhost:8100",
            manual="808d",
            alarm_code="3000",
            timeout=30,
            pdf="",
            pdf_max_mb=1.0,
            retention_days=14,
            create_backup=False,
            restore_smoke=False,
        ))
        names = [step.name for step in steps]

        self.assertEqual(
            [
                "preflight",
                "model-cache",
                "smoke",
                "regression",
                "role-console",
                "backup:list",
                "backup:dry-run",
            ],
            names,
        )
        self.assertIn("--dry-run", steps[-1].command)
        self.assertIn("--require-ollama-model", steps[0].command)

    def test_create_backup_adds_verify_latest_step(self):
        steps = standalone_acceptance.build_steps(Namespace(
            base_url="http://localhost:8100",
            manual="808d",
            alarm_code="3000",
            timeout=30,
            pdf="data/test.pdf",
            pdf_max_mb=2.0,
            retention_days=7,
            create_backup=True,
            restore_smoke=False,
            with_automation=True,
            ollama_url="http://127.0.0.1:11434",
        ))
        names = [step.name for step in steps]

        self.assertIn("backup:create", names)
        self.assertIn("n8n-workflow", names)
        self.assertIn("--with-automation", steps[0].command)
        self.assertIn("http://127.0.0.1:11434", steps[0].command)
        self.assertIn("backup:list", names)
        self.assertIn("backup:verify-latest", names)
        self.assertIn("backup:health", names)
        health = next(step for step in steps if step.name == "backup:health")
        self.assertIn("alarm_db,data,qdrant_data,n8n_data", health.command)
        self.assertNotIn("backup:restore-smoke", names)
        smoke = next(step for step in steps if step.name == "smoke")
        self.assertIn("--pdf", smoke.command)
        self.assertIn("--pdf-max-mb", smoke.command)

    def test_restore_smoke_is_explicit_opt_in(self):
        steps = standalone_acceptance.build_steps(Namespace(
            base_url="http://localhost:8100",
            manual="808d",
            alarm_code="3000",
            timeout=30,
            pdf="",
            pdf_max_mb=1.0,
            retention_days=7,
            create_backup=True,
            restore_smoke=True,
        ))
        names = [step.name for step in steps]

        self.assertIn("backup:restore-smoke", names)
        health = next(step for step in steps if step.name == "backup:health")
        self.assertIn("alarm_db,data,qdrant_data", health.command)


if __name__ == "__main__":
    unittest.main()
