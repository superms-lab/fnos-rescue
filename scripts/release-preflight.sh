#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

if test "${ALLOW_DIRTY:-0}" != 1 && test -n "$(git status --porcelain)"; then
  echo "ERROR: release preflight requires a clean worktree" >&2
  exit 2
fi

python3 - <<'PY'
from pathlib import Path
import re
pyproject = Path("pyproject.toml").read_text()
runtime = Path("src/fnos_rescue/__init__.py").read_text()
a = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
b = re.search(r'__version__ = "([^"]+)"', runtime).group(1)
if a != b:
    raise SystemExit(f"version mismatch: pyproject={a}, runtime={b}")
print(f"version {a} matches")
PY

git diff --check
./scripts/security-scan.sh
./scripts/validate-live-profile.sh
PYTHONPATH=src python3 -m unittest discover -s tests
(cd web && npm ci && npm run build && npm run audit)
rm -rf src/fnos_rescue/web_dist
cp -R web/dist src/fnos_rescue/web_dist
./scripts/clean-release.sh
./scripts/build-recovery-tools.sh
python3 -m build
./scripts/build-deb.sh
./scripts/build-fnos-package.sh
python3 scripts/generate-release-metadata.py
python3 scripts/verify-release-artifacts.py
echo "release preflight passed"
