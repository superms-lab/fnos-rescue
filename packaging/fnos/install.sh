#!/bin/sh
set -eu

test "$(id -u)" = 0 || { echo "ERROR: install requires root" >&2; exit 2; }
test -d /fs && test -d /var/apps || { echo "ERROR: fnOS was not detected" >&2; exit 2; }

SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP=/var/apps/fnos-rescue
UNIT=/etc/systemd/system/fnos-rescue-web.service
BACKUP=
if test -d "$APP"; then
  BACKUP="${APP}.backup.$(date +%Y%m%d%H%M%S)"
  mv "$APP" "$BACKUP"
fi
cleanup() {
  status=$?
  if test "$status" != 0; then
    rm -rf "$APP"
    test -n "$BACKUP" && test -d "$BACKUP" && mv "$BACKUP" "$APP"
    test -f "$APP/fnos-rescue-web.service" && install -m 0644 "$APP/fnos-rescue-web.service" "$UNIT" || true
    systemctl daemon-reload >/dev/null 2>&1 || true
    test -d "$APP" && systemctl restart fnos-rescue-web.service >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

install -d -m 0755 "$APP" "$APP/lib/python3/dist-packages" "$APP/bin"
install -d -m 0700 /var/lib/fnos-rescue
cp -R "$SOURCE/app/fnos_rescue" "$APP/lib/python3/dist-packages/fnos_rescue"
install -m 0755 "$SOURCE/app/bin/scan_btrfs_roots" "$APP/bin/scan_btrfs_roots"
install -m 0755 "$SOURCE/app/bin/fnos-rescue-btrfs" "$APP/bin/fnos-rescue-btrfs"
install -m 0755 "$SOURCE/fnos-rescue-helper" "$APP/bin/fnos-rescue-helper"
cat > "$APP/bin/fnos-rescue" <<'EOF'
#!/bin/sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/var/apps/fnos-rescue/lib/python3/dist-packages \
  exec /usr/bin/python3 -m fnos_rescue "$@"
EOF
chmod 0755 "$APP/bin/fnos-rescue"
cat > "$APP/bin/fnos-rescue-web-url" <<'EOF'
#!/bin/sh
echo "FNOS Rescue listens safely on http://127.0.0.1:8790"
echo "Remote access: ssh -L 8790:127.0.0.1:8790 USER@FNOS_HOST"
EOF
chmod 0755 "$APP/bin/fnos-rescue-web-url"
install -m 0644 "$SOURCE/fnos-rescue-web.service" "$APP/fnos-rescue-web.service"
install -m 0644 "$SOURCE/fnos-rescue-web.service" "$UNIT"
systemctl daemon-reload
systemctl enable fnos-rescue-web.service >/dev/null
systemctl restart fnos-rescue-web.service
systemctl is-active --quiet fnos-rescue-web.service
printf '%s\n' "$BACKUP" > "$APP/.previous-install"
chmod 0600 "$APP/.previous-install"
trap - EXIT INT TERM
echo "installed $APP; Web console is active on 127.0.0.1:8790"
