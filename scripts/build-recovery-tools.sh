#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${FNOS_RESCUE_TOOLS_OUT:-$ROOT/build/recovery-tools/bin}
SOURCE=${FNOS_RESCUE_BTRFS_SOURCE:-$ROOT/build/recovery-tools/btrfs-progs}
BTRFS_COMMIT=9c5987432906daebde23f9703c0f6f90c35fa9da

test "$(uname -s)" = Linux || { echo "ERROR: recovery tools require Linux" >&2; exit 2; }
command -v cc >/dev/null || { echo "ERROR: a C compiler is required" >&2; exit 2; }
command -v git >/dev/null || { echo "ERROR: git is required" >&2; exit 2; }

mkdir -p "$OUT" "$(dirname "$SOURCE")"
cc -O2 -Wall -Wextra -Werror -std=c11 \
  "$ROOT/helpers/scan_btrfs_roots.c" -o "$OUT/scan_btrfs_roots"

if test ! -d "$SOURCE/.git"; then
  rm -rf "$SOURCE"
  git clone https://github.com/kdave/btrfs-progs.git "$SOURCE"
fi
git -C "$SOURCE" fetch --tags --force origin
git -C "$SOURCE" checkout --detach "$BTRFS_COMMIT"
git -C "$SOURCE" reset --hard "$BTRFS_COMMIT"
cp "$ROOT/vendor/btrfs-progs-v7/rescue-chunk-recover.c" "$SOURCE/cmds/rescue-chunk-recover.c"
cp "$ROOT/vendor/btrfs-progs-v7/restore.c" "$SOURCE/cmds/restore.c"

if test ! -x "$SOURCE/configure"; then
  (cd "$SOURCE" && ./autogen.sh)
fi
(cd "$SOURCE" && ./configure --disable-documentation --disable-python)
make -C "$SOURCE" -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)" btrfs
install -m 0755 "$SOURCE/btrfs" "$OUT/fnos-rescue-btrfs"

"$OUT/scan_btrfs_roots" 2>&1 | grep -q '^usage:' || test "$?" = 2
"$OUT/fnos-rescue-btrfs" version
printf '%s\n' "$BTRFS_COMMIT" > "$OUT/btrfs-progs.commit"
echo "$OUT"
