import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DeploymentDocsTests(unittest.TestCase):
    def test_deployment_doc_covers_runtime_contract(self):
        text = (ROOT / "docs" / "guides" / "DEPLOYMENT.md").read_text(encoding="utf-8")
        required = [
            "python scripts/bootstrap_env.py --show-admin-password",
            "python scripts/preflight_check.py",
            "docker compose up -d",
            "ADMIN_INITIAL_PASSWORD",
            "ALARM_RAG_TRIGGER_TOKEN",
            "N8N_ENCRYPTION_KEY",
            "HF_HUB_OFFLINE=1",
            "RAG_PRELOAD_MODELS=1",
            "VECTOR_STORE=qdrant",
            "python scripts/n8n_workflow_check.py",
            "python scripts/data_maintenance.py backup-runtime",
            "python scripts/data_maintenance.py restore-runtime",
            "X-Content-Type-Options: nosniff",
            "X-Frame-Options: DENY",
            "Permissions-Policy",
        ]

        missing = [item for item in required if item not in text]
        self.assertEqual([], missing)

    def test_readme_points_to_deployment_doc_and_validation(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("docs/guides/DEPLOYMENT.md", text)
        self.assertIn("docs/plans/REUSABLE_COMPANY_TEMPLATE_PLAN_ZH_TW.md", text)
        self.assertIn("python scripts/verify_company_workflows.py", text)
        self.assertIn("python scripts/preflight_check.py", text)
        self.assertIn("--require-model-cache", text)
        self.assertIn("--require-ollama-model", text)

    def test_template_plan_tracks_remaining_acceptance(self):
        text = (ROOT / "docs/plans/REUSABLE_COMPANY_TEMPLATE_PLAN_ZH_TW.md").read_text(encoding="utf-8")
        required = [
            "gemma4:e2b",
            "PostgreSQL",
            "瀏覽器完整流程",
            "雙實例部署與還原",
            "跨批次去重",
        ]

        missing = [item for item in required if item not in text]
        self.assertEqual([], missing)

    def test_template_entrypoint_links_resolve_after_legacy_docs_cleanup(self):
        for name in ("README.md", "docs/README.md", "docs/guides/COMPANY_TEMPLATE_ZH_TW.md",
                     "docs/guides/LOCAL_OLLAMA_ZH_TW.md", "docs/plans/REUSABLE_COMPANY_TEMPLATE_PLAN_ZH_TW.md"):
            path = ROOT / name
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if target.startswith(("https://", "http://", "#")):
                    continue
                self.assertTrue((path.parent / target.split("#", 1)[0]).exists(), f"{name}: {target}")


if __name__ == "__main__":
    unittest.main()
