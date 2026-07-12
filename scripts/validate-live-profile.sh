#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
required=(
  live/config/package-lists/fnos-rescue.list.chroot
  live/config/hooks/live/010-fnos-rescue.hook.chroot
  live/config/includes.chroot/etc/systemd/system/fnos-rescue-web.service
  live/config/includes.chroot/etc/systemd/system/fnos-rescue-kiosk.service
  live/config/includes.chroot/etc/xdg/openbox/autostart
  scripts/live-session.sh
)
for path in "${required[@]}"; do
  test -s "$ROOT/$path" || { echo "missing live profile file: $path" >&2; exit 2; }
done
grep -qx btrfs-progs "$ROOT/live/config/package-lists/fnos-rescue.list.chroot"
grep -qx gddrescue "$ROOT/live/config/package-lists/fnos-rescue.list.chroot"
grep -q -- '--host 127.0.0.1' "$ROOT/live/config/includes.chroot/etc/systemd/system/fnos-rescue-web.service"
if grep -R -E 'btrfs check --repair|zero-log|mkfs\.|mdadm --create' "$ROOT/live"; then
  echo "destructive command found in live profile" >&2
  exit 2
fi
echo "live profile validation passed"
