#!/bin/sh
set -eu

attempt=0
while test "$attempt" -lt 60; do
  if curl -fsS http://127.0.0.1:8790/api/health >/dev/null && \
     systemctl is-active --quiet fnos-rescue-kiosk.service && \
     test -x /opt/fnos-rescue/bin/scan_btrfs_roots && \
     test -x /opt/fnos-rescue/bin/fnos-rescue-btrfs; then
    printf 'FNOS_RESCUE_READY web=ok kiosk=ok tools=ok\n' | tee /dev/ttyS0
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 1
done
printf 'FNOS_RESCUE_NOT_READY\n' | tee /dev/ttyS0
exit 1
