#!/usr/bin/env bash
set -euo pipefail

ARCHIVE=${1:?usage: test-fnos-package-lifecycle.sh /path/to/fnos-package.tar.gz}
test "$(id -u)" = 0 || { echo "ERROR: lifecycle test requires root" >&2; exit 2; }
test "${FNOS_RESCUE_DISPOSABLE_TEST:-}" = 1 || {
  echo "ERROR: refusing to modify /var/apps outside a disposable CI test" >&2
  exit 2
}
test -f /fs/.fnos-rescue-disposable-test || {
  echo "ERROR: disposable fnOS marker is missing" >&2
  exit 2
}
test -f "$ARCHIVE" || { echo "ERROR: package not found: $ARCHIVE" >&2; exit 2; }

WORK=$(mktemp -d)
APP=/var/apps/fnos-rescue
UNIT=/etc/systemd/system/fnos-rescue-web.service
PACKAGE_DIR=

cleanup() {
  systemctl disable --now fnos-rescue-web.service >/dev/null 2>&1 || true
  rm -f "$UNIT"
  rm -rf "$APP" /var/apps/fnos-rescue.backup.*
  systemctl daemon-reload >/dev/null 2>&1 || true
  rm -rf "$WORK"
  rm -f /fs/.fnos-rescue-disposable-test
  rmdir /fs /var/apps 2>/dev/null || true
}
trap cleanup EXIT INT TERM

tar -xzf "$ARCHIVE" -C "$WORK"
PACKAGE_DIR=$(find "$WORK" -mindepth 1 -maxdepth 1 -type d -name 'fnos-rescue_*' -print -quit)
test -n "$PACKAGE_DIR" || { echo "ERROR: package directory is missing" >&2; exit 2; }
VERSION=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$PACKAGE_DIR/manifest.json")

wait_for_health() {
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8790/api/health >/dev/null; then
      return 0
    fi
    sleep 1
  done
  systemctl status fnos-rescue-web.service --no-pager >&2 || true
  journalctl -u fnos-rescue-web.service --no-pager -n 100 >&2 || true
  return 1
}

"$PACKAGE_DIR/install.sh"
systemctl is-active --quiet fnos-rescue-web.service
wait_for_health
"$APP/bin/fnos-rescue" --version | grep -q " $VERSION$"
ss -ltn | grep -q '127\.0\.0\.1:8790'
! ss -ltn | grep -q '0\.0\.0\.0:8790'
systemctl show fnos-rescue-web.service \
  -p User -p NoNewPrivileges -p PrivateTmp -p ProtectHome -p ProtectSystem \
  >"$WORK/service-properties.txt"
grep -q '^User=root$' "$WORK/service-properties.txt"
grep -q '^NoNewPrivileges=yes$' "$WORK/service-properties.txt"
grep -q '^PrivateTmp=yes$' "$WORK/service-properties.txt"
grep -q '^ProtectSystem=strict$' "$WORK/service-properties.txt"
"$APP/bin/fnos-rescue-helper" fnos-detect >/dev/null
if "$APP/bin/fnos-rescue-helper" job-run >/dev/null 2>&1; then
  echo "ERROR: root helper accepted job-run" >&2
  exit 1
fi
if "$APP/bin/fnos-rescue-helper" shell >/dev/null 2>&1; then
  echo "ERROR: root helper accepted shell" >&2
  exit 1
fi
test -z "$(find "$APP" \( -name __pycache__ -o -name '*.pyc' \) -print -quit)"

printf 'previous-install\n' >"$APP/rollback-sentinel"
"$PACKAGE_DIR/install.sh"
BACKUP=$(cat "$APP/.previous-install")
test -n "$BACKUP" && test -f "$BACKUP/rollback-sentinel"
test ! -e "$APP/rollback-sentinel"
wait_for_health

"$PACKAGE_DIR/uninstall.sh"
test -f "$APP/rollback-sentinel"
wait_for_health
"$APP/bin/fnos-rescue" --version | grep -q " $VERSION$"

"$PACKAGE_DIR/uninstall.sh"
test ! -e "$APP"
test ! -e "$UNIT"
test -d /var/lib/fnos-rescue
if systemctl is-active --quiet fnos-rescue-web.service; then
  echo "ERROR: fnOS Web service remained active after final uninstall" >&2
  exit 1
fi
test -z "$(find /var/apps -maxdepth 1 -name 'fnos-rescue.backup.*' -print -quit)"
echo "fnOS package lifecycle passed for version $VERSION"
