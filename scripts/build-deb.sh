#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=$(PYTHONPATH="$ROOT/src" python3 -c 'import fnos_rescue; print(fnos_rescue.__version__)')
STAGE="$ROOT/build/deb/fnos-rescue_${VERSION}_all"
OUTPUT="$ROOT/dist/fnos-rescue_${VERSION}_all.deb"

command -v dpkg-deb >/dev/null || { echo "ERROR: dpkg-deb is required" >&2; exit 2; }
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/lib/python3/dist-packages" "$STAGE/usr/bin" "$ROOT/dist"
sed "s/^Version: .*/Version: $VERSION/" "$ROOT/packaging/debian/control" > "$STAGE/DEBIAN/control"
cp -R "$ROOT/src/fnos_rescue" "$STAGE/usr/lib/python3/dist-packages/fnos_rescue"
install -m 0755 "$ROOT/packaging/debian/fnos-rescue" "$STAGE/usr/bin/fnos-rescue"
ln -s fnos-rescue "$STAGE/usr/bin/rescuectl"
dpkg-deb --build --root-owner-group "$STAGE" "$OUTPUT"
echo "$OUTPUT"
