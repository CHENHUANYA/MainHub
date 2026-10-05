from argparse import Namespace

from scripts import local_validation_bundle


def make_args(**overrides):
    args = {
        "base_url": "http://localhost:8100",
        "manual": "808d",
        "alarm_code": "3000",
        "timeout": 30,
        "pdf": "",
        "pdf_max_mb": 1.0,
        "retention_days": 14,
        "create_backup": False,
        "restore_smoke": False,
        "require_model_cache": True,
        "ui_report": "tests_tmp/browser_e2e/browser_e2e_report.json",
        "ui_screenshots": "tests_tmp/browser_e2e/screenshots",
        "backup_max_age_hours": 72.0,
        "backup_components": "",
    }
    args.update(overrides)
    return Namespace(**args)


def test_bundle_runs_required_local_reliability_checks():
    steps = local_validation_bundle.build_steps(make_args())
    names = [step.name for step in steps]

    assert names == [
        "preflight",
        "standalone-acceptance",
        "ui-evidence",
        "backup-health",
    ]
    assert "preflight_check.py" in str(steps[0].command)
    assert "--require-model-cache" in steps[0].command
    assert "--require-ollama-model" in steps[0].command
    assert "standalone_acceptance.py" in str(steps[1].command)
    assert "ui_evidence_check.py" in str(steps[2].command)
    assert "backup-health" in steps[3].command
    assert "--verify" in steps[3].command
    assert "alarm_db,data,qdrant_data" in steps[3].command


def test_bundle_forwards_optional_automation_and_local_ollama_url():
    steps = local_validation_bundle.build_steps(make_args(with_automation=True, ollama_url="http://127.0.0.1:11434"))
    assert "n8n-workflow" in [step.name for step in steps]
    for step in steps:
        if step.name in {"preflight", "standalone-acceptance"}:
            assert "--with-automation" in step.command
            assert "http://127.0.0.1:11434" in step.command
    assert "alarm_db,data,qdrant_data,n8n_data" in steps[-1].command


def test_bundle_forwards_restore_smoke_only_when_opted_in():
    default_steps = local_validation_bundle.build_steps(make_args())
    opt_in_steps = local_validation_bundle.build_steps(make_args(create_backup=True, restore_smoke=True))

    default_acceptance = next(step for step in default_steps if step.name == "standalone-acceptance")
    opt_in_acceptance = next(step for step in opt_in_steps if step.name == "standalone-acceptance")
    opt_in_restore = opt_in_steps[-1]

    assert "--restore-smoke" not in default_acceptance.command
    assert "--restore-smoke" not in opt_in_acceptance.command
    assert "--create-backup" in opt_in_acceptance.command
    assert opt_in_restore.name == "restore-smoke"
    assert "restore-smoke" in opt_in_restore.command
