#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=$(PYTHONPATH="$ROOT/src" python3 -c 'import fnos_rescue; print(fnos_rescue.__version__)')
ARCH=${DEB_ARCH:-$(dpkg --print-architecture)}
TOOLS=${FNOS_RESCUE_TOOLS_DIR:-$ROOT/build/recovery-tools/bin}
STAGE="$ROOT/build/deb/fnos-rescue_${VERSION}_${ARCH}"
OUTPUT="$ROOT/dist/fnos-rescue_${VERSION}_${ARCH}.deb"

command -v dpkg-deb >/dev/null || { echo "ERROR: dpkg-deb is required" >&2; exit 2; }
for tool in scan_btrfs_roots fnos-rescue-btrfs; do
  test -x "$TOOLS/$tool" || { echo "ERROR: missing recovery tool: $TOOLS/$tool" >&2; exit 2; }
done
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/lib/python3/dist-packages" "$STAGE/usr/bin" "$STAGE/usr/lib/fnos-rescue/bin" "$ROOT/dist"
sed -e "s/^Version: .*/Version: $VERSION/" -e "s/^Architecture: .*/Architecture: $ARCH/" "$ROOT/packaging/debian/control" > "$STAGE/DEBIAN/control"
cp -R "$ROOT/src/fnos_rescue" "$STAGE/usr/lib/python3/dist-packages/fnos_rescue"
find "$STAGE/usr/lib/python3/dist-packages" -type d -name __pycache__ -prune -exec rm -rf {} +
install -m 0755 "$TOOLS/scan_btrfs_roots" "$STAGE/usr/lib/fnos-rescue/bin/scan_btrfs_roots"
install -m 0755 "$TOOLS/fnos-rescue-btrfs" "$STAGE/usr/lib/fnos-rescue/bin/fnos-rescue-btrfs"
install -m 0755 "$ROOT/packaging/debian/fnos-rescue" "$STAGE/usr/bin/fnos-rescue"
ln -s fnos-rescue "$STAGE/usr/bin/rescuectl"
dpkg-deb --build --root-owner-group "$STAGE" "$OUTPUT"
echo "$OUTPUT"
