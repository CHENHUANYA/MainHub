from pathlib import Path

from scripts.export_company_template import bundle_files
from scripts.export_company_template import main


def test_template_bundle_excludes_runtime_secrets_and_historical_outputs(tmp_path: Path):
    included = ["main.py", "Dockerfile", ".env.example", "services/company_config.py",
                "templates/company.compressor-demo.json", "static/alarm_app.js",
                "docs/guides/COMPANY_TEMPLATE_ZH_TW.md"]
    excluded = [".env", ".env.postgresql", "credentials.json", "alarm_db/users.json",
                "alarm_db/system_settings.json", "data/private.pdf", "backups/database.sql",
                "hf_cache/model.json", "qdrant_data/config.json", "n8n_data/config.json",
                "outputs/report.md", "docs/reports/old.md", "docs/plans/old.md",
                "services/__pycache__/cache.pyc", "templates/.env"]
    for name in included + excluded:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("example", encoding="utf-8")
    actual = {path.relative_to(tmp_path).as_posix() for path in bundle_files(tmp_path)}
    assert actual == set(included)


def test_exported_readme_links_model_guide_and_includes_excel_preview(tmp_path, monkeypatch):
    from zipfile import ZipFile
    output = tmp_path / "template.zip"
    monkeypatch.setattr("sys.argv", ["export_company_template.py", "--output", str(output)])
    main()
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert "(docs/guides/LOCAL_OLLAMA_ZH_TW.md)" in archive.read("README.md").decode("utf-8")
        assert "docs/guides/LOCAL_OLLAMA_ZH_TW.md" in archive.namelist()
        assert "(docs/guides/COMPANY_DEPLOYMENT_SOP_ZH_TW.md)" in archive.read("README.md").decode("utf-8")
        assert "docs/guides/COMPANY_DEPLOYMENT_SOP_ZH_TW.md" in archive.namelist()
        assert "(docs/guides/RELEASE_NOTES_2026-09-28_ZH_TW.md)" in archive.read("README.md").decode("utf-8")
        assert "docs/guides/RELEASE_NOTES_2026-09-28_ZH_TW.md" in archive.namelist()
        assert "static/js/modules/excel-import.js" in archive.namelist()
        assert "static/css/excel-import.css" in archive.namelist()
        archive.extractall(tmp_path / 'receiver')
    from scripts.verify_template_bundle import verify
    receiver = tmp_path / 'receiver'
    result = verify(receiver)
    assert result['status'] == 'PASS'
    assert result['checked_files'] > 100
    (receiver / 'my-company.json').write_text('{}')
    assert verify(receiver)['status'] == 'PASS'
    (receiver / 'services/company_config.py').write_text('# changed')
    assert verify(receiver)['changed'] == ['services/company_config.py']
    (receiver / 'static/css/excel-import.css').unlink()
    assert verify(receiver)['missing'] == ['static/css/excel-import.css']


def test_template_manifest_rejects_parent_paths(tmp_path):
    import json
    import pytest
    from scripts.verify_template_bundle import verify
    (tmp_path / 'template-manifest.json').write_text(json.dumps({
        'schema_version': 1, 'files': {'../outside.py': 'anything'},
    }))
    with pytest.raises(ValueError, match='inside'):
        verify(tmp_path)
