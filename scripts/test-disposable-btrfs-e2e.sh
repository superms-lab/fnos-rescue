#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
test "$(uname -s)" = Linux || { echo "SKIP: disposable Btrfs E2E requires Linux"; exit 0; }
test "$(id -u)" = 0 || { echo "ERROR: disposable Btrfs E2E requires root" >&2; exit 2; }

WORK=$(mktemp -d /tmp/fnos-rescue-e2e.XXXXXX)
SOURCE_MOUNT="$WORK/source"
DESTINATION_MOUNT="$WORK/destination"
SOURCE_LOOP=""
DESTINATION_LOOP=""

cleanup() {
  set +e
  mountpoint -q "$SOURCE_MOUNT" && umount "$SOURCE_MOUNT"
  mountpoint -q "$DESTINATION_MOUNT" && umount "$DESTINATION_MOUNT"
  test -z "$SOURCE_LOOP" || losetup -d "$SOURCE_LOOP"
  test -z "$DESTINATION_LOOP" || losetup -d "$DESTINATION_LOOP"
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

mkdir -p "$SOURCE_MOUNT" "$DESTINATION_MOUNT"
truncate -s 512M "$WORK/source.img"
truncate -s 256M "$WORK/destination.img"
SOURCE_LOOP=$(losetup --find --show "$WORK/source.img")
DESTINATION_LOOP=$(losetup --find --show "$WORK/destination.img")

mkfs.btrfs -q -f -L FNOS_RESCUE_SOURCE "$SOURCE_LOOP"
mkfs.ext4 -q -F -L FNOS_RESCUE_DESTINATION "$DESTINATION_LOOP"
mount "$SOURCE_LOOP" "$SOURCE_MOUNT"
mkdir -p "$SOURCE_MOUNT/Photos/2026"
printf '%s\n' 'FNOS Rescue disposable read-only source' > "$SOURCE_MOUNT/Photos/2026/known.txt"
sync
umount "$SOURCE_MOUNT"

SOURCE_BEFORE=$(sha256sum "$WORK/source.img" | awk '{print $1}')
blockdev --setro "$SOURCE_LOOP"
blockdev --setro "$SOURCE_LOOP"
test "$(blockdev --getro "$SOURCE_LOOP")" = 1
mount -o ro,nosuid,nodev "$SOURCE_LOOP" "$SOURCE_MOUNT"
mount -o nosuid,nodev "$DESTINATION_LOOP" "$DESTINATION_MOUNT"

EXPECTED_SIZE=$(stat -c '%s' "$SOURCE_MOUNT/Photos/2026/known.txt")
EXPECTED_SHA=$(sha256sum "$SOURCE_MOUNT/Photos/2026/known.txt" | awk '{print $1}')
printf '原始大小(bytes)\t相对路径\tSHA256\n%s\t%s\t%s\n' \
  "$EXPECTED_SIZE" 'Photos/2026/known.txt' "$EXPECTED_SHA" > "$WORK/manifest.tsv"

FNOS_RESCUE_DESTINATION_ROOTS="$WORK" PYTHONPATH="$ROOT/src" \
  python3 "$ROOT/helpers/copy_validated_paths.py" \
  "$WORK/manifest.tsv" "$SOURCE_MOUNT" "$DESTINATION_MOUNT" "$WORK/copy-results.tsv" \
  --source-device "$SOURCE_LOOP"
cmp "$SOURCE_MOUNT/Photos/2026/known.txt" "$DESTINATION_MOUNT/Photos/2026/known.txt"
grep -q '^成功' "$WORK/copy-results.tsv"

PYTHONPATH="$ROOT/src" python3 - "$SOURCE_LOOP" "$DESTINATION_MOUNT/Photos/2026/known.txt" "$EXPECTED_SHA" <<'PY'
import sys
from fnos_rescue.plugins.fnos_btrfs import FnosBtrfsPlugin
from fnos_rescue.verify import verify_file

evidence = FnosBtrfsPlugin().probe(sys.argv[1])
if not any(mirror.get("valid_magic") and mirror.get("valid_checksum") for mirror in evidence["mirrors"]):
    raise SystemExit("no valid Btrfs superblock mirror was detected")
result = verify_file(sys.argv[2], expected_sha256=sys.argv[3])
if result.classification != "validated":
    raise SystemExit(f"destination validation failed: {result}")
PY

sync
umount "$SOURCE_MOUNT"
SOURCE_AFTER=$(sha256sum "$WORK/source.img" | awk '{print $1}')
test "$SOURCE_BEFORE" = "$SOURCE_AFTER"
echo "disposable Btrfs E2E passed; source image remained byte-identical"
