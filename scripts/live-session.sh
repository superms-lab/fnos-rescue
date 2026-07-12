#!/bin/sh
set -eu

case "${1:-start-ui}" in
  start-ui)
    systemctl start fnos-rescue-web.service
    ;;
  doctor)
    PYTHONPATH=/opt/fnos-rescue/src exec python3 -m fnos_rescue doctor
    ;;
  *)
    echo "usage: fnos-rescue-session {start-ui|doctor}" >&2
    exit 2
    ;;
esac
