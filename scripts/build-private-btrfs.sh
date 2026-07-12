#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/btrfs-progs-v7" >&2
  exit 2
fi

source_tree=$(cd "$1" && pwd)
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

if [[ ! -f "$source_tree/Makefile" || ! -d "$source_tree/cmds" ]]; then
  echo "not a configured btrfs-progs source tree: $source_tree" >&2
  exit 2
fi

cp "$repo_root/vendor/btrfs-progs-v7/rescue-chunk-recover.c" \
  "$source_tree/cmds/rescue-chunk-recover.c"
cp "$repo_root/vendor/btrfs-progs-v7/restore.c" "$source_tree/cmds/restore.c"

make -C "$source_tree" -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)" btrfs
echo "private recovery binary: $source_tree/btrfs"
