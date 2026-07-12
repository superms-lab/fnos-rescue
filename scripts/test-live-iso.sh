#!/usr/bin/env bash
set -euo pipefail

ISO=${1:?usage: test-live-iso.sh /path/to/fnos-rescue.iso}
test -f "$ISO" || { echo "ERROR: ISO not found: $ISO" >&2; exit 2; }
command -v qemu-system-x86_64 >/dev/null || { echo "ERROR: qemu-system-x86_64 is required" >&2; exit 2; }
if test -n "${FNOS_RESCUE_LIVE_DIAGNOSTICS_DIR:-}"; then
  WORK=$FNOS_RESCUE_LIVE_DIAGNOSTICS_DIR
  mkdir -p "$WORK"
else
  WORK=$(mktemp -d)
  trap 'rm -rf "$WORK"' EXIT
fi

boot_and_check() {
  name=$1
  shift
  log="$WORK/$name.log"
  monitor="$WORK/$name.monitor"
  mkfifo "$monitor"
  exec 9<>"$monitor"
  qemu-system-x86_64 -machine accel=tcg -cpu max -m 3072 -smp 2 \
    -drive "file=$ISO,media=cdrom,readonly=on" -boot d \
    -display none -serial "file:$log" -monitor stdio -no-reboot "$@" \
    <&9 >"$WORK/$name.qemu.log" 2>&1 &
  pid=$!

  # Debian Live's BIOS and UEFI menus are graphical. Press Enter through the
  # QEMU monitor so a headless CI runner actually boots the default entry.
  sleep 3
  printf 'sendkey ret\n' >&9
  sleep 7
  printf 'sendkey ret\n' >&9

  deadline=$((SECONDS + 240))
  while kill -0 "$pid" 2>/dev/null && test "$SECONDS" -lt "$deadline"; do
    if grep -q 'FNOS_RESCUE_READY web=ok kiosk=ok tools=ok' "$log" 2>/dev/null; then
      printf 'quit\n' >&9
      wait "$pid" || true
      exec 9>&-
      echo "$name boot readiness passed"
      return 0
    fi
    sleep 2
  done

  # Capture the last VGA frame before stopping QEMU. Serial output can remain
  # empty when a graphical boot menu or firmware error blocks the guest.
  printf 'screendump %s\n' "$WORK/$name.ppm" >&9 2>/dev/null || true
  sleep 1
  printf 'quit\n' >&9 2>/dev/null || true
  wait "$pid" || true
  exec 9>&-
  if ! grep -q 'FNOS_RESCUE_READY web=ok kiosk=ok tools=ok' "$log"; then
    tail -200 "$log" >&2
    tail -100 "$WORK/$name.qemu.log" >&2
    echo "ERROR: $name boot did not reach FNOS Rescue readiness" >&2
    return 1
  fi
}

status=0
if ! boot_and_check bios; then
  status=1
fi
OVMF=$(find /usr/share/OVMF /usr/share/ovmf -type f \( -name 'OVMF_CODE.fd' -o -name 'OVMF_CODE_4M.fd' \) 2>/dev/null | head -1)
test -n "$OVMF" || { echo "ERROR: OVMF firmware is required" >&2; exit 2; }
case $(basename "$OVMF") in
  OVMF_CODE_4M.fd) OVMF_VARS=$(dirname "$OVMF")/OVMF_VARS_4M.fd ;;
  *) OVMF_VARS=$(dirname "$OVMF")/OVMF_VARS.fd ;;
esac
test -f "$OVMF_VARS" || { echo "ERROR: OVMF variable store is required" >&2; exit 2; }
cp "$OVMF_VARS" "$WORK/uefi-vars.fd"
if ! boot_and_check uefi \
  -drive "if=pflash,format=raw,readonly=on,file=$OVMF" \
  -drive "if=pflash,format=raw,file=$WORK/uefi-vars.fd"; then
  status=1
fi
exit "$status"
