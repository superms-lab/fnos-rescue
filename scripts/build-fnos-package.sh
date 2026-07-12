#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=$(PYTHONPATH="$ROOT/src" python3 -c 'import fnos_rescue; print(fnos_rescue.__version__)')
ARCH=${FNOS_ARCH:-$(uname -m)}
TOOLS=${FNOS_RESCUE_TOOLS_DIR:-$ROOT/build/recovery-tools/bin}
STAGE="$ROOT/build/fnos/fnos-rescue_${VERSION}_${ARCH}"
OUTPUT="$ROOT/dist/fnos-rescue_${VERSION}_fnos_${ARCH}.tar.gz"

rm -rf "$STAGE"
mkdir -p "$STAGE/app" "$ROOT/dist"
for tool in scan_btrfs_roots fnos-rescue-btrfs; do
  test -x "$TOOLS/$tool" || { echo "ERROR: missing recovery tool: $TOOLS/$tool" >&2; exit 2; }
done
cp -R "$ROOT/src/fnos_rescue" "$STAGE/app/fnos_rescue"
find "$STAGE/app/fnos_rescue" -type d -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$STAGE/app/bin"
install -m 0755 "$TOOLS/scan_btrfs_roots" "$STAGE/app/bin/scan_btrfs_roots"
install -m 0755 "$TOOLS/fnos-rescue-btrfs" "$STAGE/app/bin/fnos-rescue-btrfs"
if test -d "$ROOT/web/dist"; then
  cp -R "$ROOT/web/dist" "$STAGE/app/fnos_rescue/web_dist"
fi
install -m 0755 "$ROOT/packaging/fnos/install.sh" "$STAGE/install.sh"
install -m 0755 "$ROOT/packaging/fnos/uninstall.sh" "$STAGE/uninstall.sh"
install -m 0755 "$ROOT/packaging/fnos/fnos-rescue-helper" "$STAGE/fnos-rescue-helper"
printf '{"name":"FNOS Rescue","version":"%s","architecture":"%s","os":"fnOS"}\n' \
  "$VERSION" "$ARCH" > "$STAGE/manifest.json"
tar -C "$(dirname "$STAGE")" -czf "$OUTPUT" "$(basename "$STAGE")"
echo "$OUTPUT"
