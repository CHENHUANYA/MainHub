"""Check that the packaged template files have not changed during company setup.

The manifest detects accidental changes; it is not a signed supply-chain attestation.
Generated company settings, credentials and runtime data are outside this manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def verify(root: Path) -> dict:
    root = root.resolve()
    manifest_path = root / 'template-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or not isinstance(manifest.get('files'), dict) or not manifest['files']:
        raise ValueError('Invalid template manifest')
    changed, missing = [], []
    for name, expected in manifest['files'].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
            raise ValueError('Manifest path must stay inside the template')
        path = (root / name).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError('Manifest path must stay inside the template')
        if not path.is_file():
            missing.append(name)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            changed.append(name)
    return {'status': 'PASS' if not changed and not missing else 'FAIL',
            'checked_files': len(manifest['files']), 'changed': changed, 'missing': missing,
            'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = verify(args.root)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Template verification failed: {exc}\n')
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
