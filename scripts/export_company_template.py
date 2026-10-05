"""Export a source deployment bundle without copying company runtime data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = {"db", "migrations", "repositories", "routes", "services", "static", "templates", "deploy", "scripts"}
SOURCE_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".yml", ".yaml", ".toml", ".ini", ".txt", ".md", ".conf", ".sh", ".ps1"}
ROOT_NAMES = {"Dockerfile", "Dockerfile.postgresql", ".dockerignore", ".gitignore", ".env.example", ".env.postgresql.example"}
ROOT_SUFFIXES = {".py", ".html", ".toml", ".ini", ".txt", ".yml"}
EXAMPLES = {"mock_data/n8n_mock_workflow.json", "mock_data/machine_mapping_example.json"}


def bundle_files(root: Path = ROOT) -> list[Path]:
    files = []
    candidates = list(root.iterdir())
    for directory in sorted(SOURCE_DIRS | {"docs/guides", "docs/operations"}):
        base = root / directory
        if base.is_dir() and not base.is_symlink():
            candidates.extend(base.rglob("*"))
    candidates.extend(root / example for example in EXAMPLES)
    for path in candidates:
        relative = path.relative_to(root)
        # Do not export symlinks, generated files, or unrecognized runtime directories.
        if path.is_symlink() or not path.is_file() or "__pycache__" in relative.parts:
            continue
        if any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
            continue
        if len(relative.parts) == 1:
            include = path.name in ROOT_NAMES or (path.suffix in ROOT_SUFFIXES and not path.name.startswith('.'))
        elif relative.parts[0] in SOURCE_DIRS:
            include = path.suffix in SOURCE_SUFFIXES and not any(part.startswith('.') for part in relative.parts)
        else:
            include = relative.parts[:2] in {("docs", "guides"), ("docs", "operations")}
            include = include and path.suffix == ".md"
            include = include or relative.as_posix() in EXAMPLES
        if include:
            files.append(path)
    return sorted(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = bundle_files()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, "x", ZIP_DEFLATED) as archive:
        guide = (ROOT / "docs/guides/COMPANY_TEMPLATE_ZH_TW.md").read_text(encoding="utf-8")
        # The guide becomes a root README in the bundle; keep its model link usable.
        readme = guide.replace("(LOCAL_OLLAMA_ZH_TW.md)", "(docs/guides/LOCAL_OLLAMA_ZH_TW.md)")
        readme = readme.replace("(COMPANY_DEPLOYMENT_SOP_ZH_TW.md)", "(docs/guides/COMPANY_DEPLOYMENT_SOP_ZH_TW.md)")
        readme = readme.replace("(RAG_DEMO_ACCEPTANCE_ZH_TW.md)", "(docs/guides/RAG_DEMO_ACCEPTANCE_ZH_TW.md)")
        readme = readme.replace("(RELEASE_NOTES_2026-09-28_ZH_TW.md)", "(docs/guides/RELEASE_NOTES_2026-09-28_ZH_TW.md)")
        archive.writestr("README.md", readme)
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr('template-manifest.json', json.dumps({
            'schema_version': 1,
            'files': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        }, indent=2))
    print(f"Exported {len(files)} source files to {args.output}")
    print('SHA256: ' + hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
