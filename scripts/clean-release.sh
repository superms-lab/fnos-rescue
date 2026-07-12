#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rm -rf "$ROOT/dist" "$ROOT/build"
find "$ROOT/src" "$ROOT/tests" "$ROOT/helpers" "$ROOT/scripts" \
  -type d -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$ROOT/dist"
echo "release build directories cleaned"
