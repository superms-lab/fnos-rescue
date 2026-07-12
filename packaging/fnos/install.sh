#!/bin/sh
set -eu

test "$(id -u)" = 0 || { echo "ERROR: install requires root" >&2; exit 2; }
test -d /fs && test -d /var/apps || { echo "ERROR: fnOS was not detected" >&2; exit 2; }

SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP=/var/apps/fnos-rescue
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
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

install -d -m 0755 "$APP" "$APP/lib/python3/dist-packages" "$APP/bin"
cp -R "$SOURCE/app/fnos_rescue" "$APP/lib/python3/dist-packages/fnos_rescue"
install -m 0755 "$SOURCE/app/bin/scan_btrfs_roots" "$APP/bin/scan_btrfs_roots"
install -m 0755 "$SOURCE/app/bin/fnos-rescue-btrfs" "$APP/bin/fnos-rescue-btrfs"
install -m 0755 "$SOURCE/fnos-rescue-helper" "$APP/bin/fnos-rescue-helper"
cat > "$APP/bin/fnos-rescue" <<'EOF'
#!/bin/sh
PYTHONPATH=/var/apps/fnos-rescue/lib/python3/dist-packages exec /usr/bin/python3 -m fnos_rescue "$@"
EOF
chmod 0755 "$APP/bin/fnos-rescue"
printf '%s\n' "$BACKUP" > "$APP/.previous-install"
chmod 0600 "$APP/.previous-install"
trap - EXIT INT TERM
echo "installed $APP"
