#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
command -v lb >/dev/null || { echo "ERROR: install live-build first" >&2; exit 2; }
test "$(uname -s)" = Linux || { echo "ERROR: ISO builds require Debian/Ubuntu Linux" >&2; exit 2; }
"$ROOT/scripts/validate-live-profile.sh"
(cd "$ROOT/web" && npm ci && npm run build)

WORK="$ROOT/build/live"
rm -rf "$WORK"
mkdir -p "$WORK/config" "$ROOT/dist"
cp -R "$ROOT/live/config/." "$WORK/config/"
mkdir -p "$WORK/config/includes.chroot/opt/fnos-rescue"
cp -R "$ROOT/src" "$ROOT/web" "$ROOT/scripts" "$WORK/config/includes.chroot/opt/fnos-rescue/"
rm -rf "$WORK/config/includes.chroot/opt/fnos-rescue/web/node_modules"

cd "$WORK"
lb config noauto \
  --ignore-system-defaults \
  --mode debian \
  --distribution bookworm \
  --architectures amd64 \
  --binary-images iso-hybrid \
  --archive-areas "main contrib non-free-firmware" \
  --keyring-packages "debian-archive-keyring" \
  --security false \
  --mirror-bootstrap "https://deb.debian.org/debian" \
  --mirror-chroot "https://deb.debian.org/debian" \
  --mirror-chroot-security "https://security.debian.org/debian-security" \
  --mirror-binary "https://deb.debian.org/debian" \
  --mirror-binary-security "https://security.debian.org/debian-security" \
  --bootappend-live "boot=live components hostname=fnos-rescue username=user"
sudo lb build
ISO=$(find . -maxdepth 1 -name 'live-image-*.hybrid.iso' -print -quit)
test -n "$ISO"
install -m 0644 "$ISO" "$ROOT/dist/fnos-rescue-live-amd64.iso"
(cd "$ROOT/dist" && sha256sum fnos-rescue-live-amd64.iso > fnos-rescue-live-amd64.iso.sha256)
echo "$ROOT/dist/fnos-rescue-live-amd64.iso"
