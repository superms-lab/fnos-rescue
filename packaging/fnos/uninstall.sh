#!/bin/sh
set -eu

test "$(id -u)" = 0 || { echo "ERROR: uninstall requires root" >&2; exit 2; }
APP=/var/apps/fnos-rescue
test -d "$APP" || { echo "fnos-rescue is not installed"; exit 0; }
BACKUP=$(cat "$APP/.previous-install" 2>/dev/null || true)
rm -rf "$APP"
if test -n "$BACKUP" && test -d "$BACKUP"; then
  mv "$BACKUP" "$APP"
  echo "restored previous install"
else
  echo "uninstalled fnos-rescue"
fi
