#!/bin/sh
set -eu

test "$(id -u)" = 0 || { echo "ERROR: uninstall requires root" >&2; exit 2; }
APP=/var/apps/fnos-rescue
UNIT=/etc/systemd/system/fnos-rescue-web.service
test -d "$APP" || { echo "fnos-rescue is not installed"; exit 0; }
BACKUP=$(cat "$APP/.previous-install" 2>/dev/null || true)
systemctl disable --now fnos-rescue-web.service >/dev/null 2>&1 || true
rm -f "$UNIT"
systemctl daemon-reload >/dev/null 2>&1 || true
rm -rf "$APP"
if test -n "$BACKUP" && test -d "$BACKUP"; then
  mv "$BACKUP" "$APP"
  test -f "$APP/fnos-rescue-web.service" && install -m 0644 "$APP/fnos-rescue-web.service" "$UNIT"
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl enable --now fnos-rescue-web.service >/dev/null 2>&1 || true
  echo "restored previous install"
else
  echo "uninstalled fnos-rescue; recovery cases remain in /var/lib/fnos-rescue"
fi
