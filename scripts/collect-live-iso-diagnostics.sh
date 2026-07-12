#!/usr/bin/env bash
set -euo pipefail

ISO=${1:?usage: collect-live-iso-diagnostics.sh /path/to/fnos-rescue.iso output-directory}
OUT=${2:?usage: collect-live-iso-diagnostics.sh /path/to/fnos-rescue.iso output-directory}
test -f "$ISO" || { echo "ERROR: ISO not found: $ISO" >&2; exit 2; }
command -v xorriso >/dev/null || { echo "ERROR: xorriso is required" >&2; exit 2; }

mkdir -p "$OUT/iso-tree"
xorriso -indev "$ISO" -report_el_torito plain >"$OUT/el-torito.txt" 2>&1
xorriso -indev "$ISO" -find / -type f -exec lsdl >"$OUT/file-list.txt" 2>&1

for path in /isolinux /boot/grub /EFI; do
  destination="$OUT/iso-tree${path}"
  if xorriso -indev "$ISO" -ls "$path" >/dev/null 2>&1; then
    mkdir -p "$(dirname "$destination")"
    xorriso -osirrox on -indev "$ISO" -extract "$path" "$destination" \
      >"$OUT/extract-$(basename "$path").log" 2>&1
  fi
done

{
  echo "ISO: $ISO"
  sha256sum "$ISO"
  echo
  echo "Boot configuration files:"
  find "$OUT/iso-tree" -type f \
    \( -name '*.cfg' -o -name '*.conf' -o -name 'grub.cfg' -o -name 'menu.cfg' \) \
    -print | sort
} >"$OUT/summary.txt"

: >"$OUT/boot-configs.txt"
while IFS= read -r config; do
  {
    echo
    echo "===== ${config#"$OUT/iso-tree"} ====="
    sed -n '1,240p' "$config"
  } >>"$OUT/boot-configs.txt"
done < <(
  find "$OUT/iso-tree" -type f \
    \( -name '*.cfg' -o -name '*.conf' -o -name 'grub.cfg' -o -name 'menu.cfg' \) \
    -print | sort
)

if grep -R -n -E '@(KERNEL|LINUX|INITRD|APPEND_LIVE|LB_BOOTAPPEND)' "$OUT/iso-tree/isolinux" >"$OUT/isolinux-placeholders.txt"; then
  cat "$OUT/isolinux-placeholders.txt" >&2
  echo "ERROR: unresolved live-build placeholders remain in BIOS boot configuration" >&2
  exit 1
fi
if grep -q 'vesamenu\.c32' "$OUT/iso-tree/isolinux/isolinux.cfg" \
  && ! test -f "$OUT/iso-tree/isolinux/vesamenu.c32"; then
  echo "ERROR: BIOS configuration references missing vesamenu.c32" >&2
  exit 1
fi

cat "$OUT/summary.txt"
cat "$OUT/boot-configs.txt"
