#!/usr/bin/env bash
set -euo pipefail

ISO=${1:?usage: test-live-iso.sh /path/to/fnos-rescue.iso}
test -f "$ISO" || { echo "ERROR: ISO not found: $ISO" >&2; exit 2; }
command -v qemu-system-x86_64 >/dev/null || { echo "ERROR: qemu-system-x86_64 is required" >&2; exit 2; }
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

boot_and_check() {
  name=$1
  shift
  log="$WORK/$name.log"
  set +e
  timeout 180 qemu-system-x86_64 -machine accel=tcg -cpu max -m 3072 -smp 2 \
    -drive "file=$ISO,media=cdrom,readonly=on" -boot d \
    -display none -serial stdio -monitor none -no-reboot "$@" >"$log" 2>&1
  status=$?
  set -e
  if ! grep -q 'FNOS_RESCUE_READY web=ok kiosk=ok tools=ok' "$log"; then
    tail -200 "$log" >&2
    echo "ERROR: $name boot did not reach FNOS Rescue readiness (qemu status $status)" >&2
    return 1
  fi
  echo "$name boot readiness passed"
}

boot_and_check bios
OVMF=$(find /usr/share/OVMF /usr/share/ovmf -type f \( -name 'OVMF_CODE.fd' -o -name 'OVMF_CODE_4M.fd' \) 2>/dev/null | head -1)
test -n "$OVMF" || { echo "ERROR: OVMF firmware is required" >&2; exit 2; }
boot_and_check uefi -bios "$OVMF"
