---
name: recover-fnos-btrfs-disks
description: Recover deleted or unreadable FNOS Basic-disk Btrfs volumes with the FNOS Rescue CLI and read-only Linux tooling. Use when FNOS deletion leaves a disk detectable but unmountable, UFS shows names and sizes but exports do not open, Btrfs primary supers or chunk roots are blank, or a user needs safe directory-level extraction to another disk.
---

# Recover FNOS Btrfs disks

Prioritize content recovery over forcing the original disk to mount. Treat the source as
irreplaceable evidence and reconstructed metadata as disposable.

## Enforce safety

- Identify the source by model, serial, capacity, and topology before changing device state.
- Set the whole disk, partition, MD/LVM, and loop layers read-only and verify every layer.
- Never restore onto the source or a filesystem backed by the source.
- Write altered superblocks, chunk trees, or experimental metadata only to an image or QCOW2
  overlay.
- Never run repair, formatting, RAID creation, log clearing, or read-write mounts on the source.
- If physical I/O errors occur, stop exploration and image with GNU ddrescue plus a mapfile.

## Run the workflow

1. Run `fnos-rescue inspect DEVICE` and record the stable serial.
2. Run `fnos-rescue protect DEVICE --confirm-serial SERIAL --dry-run`, review it, then repeat
   without `--dry-run` as root.
3. Inspect mdadm metadata, data offsets, and the Btrfs start offset. Assemble only read-only.
4. Expose the Btrfs view through a read-only loop device.
5. Run `fnos-rescue btrfs-probe LOOP` to inspect all three super mirrors.
6. Read `references/case-patterns.md` to select the narrowest evidence-driven strategy.
7. Save historical roots and persistent chunk mappings. Do not repeat full scans when a cache
   exists.
8. Create a QCOW2 overlay before seeding historical roots or synthetic metadata.
9. List paths, let the user choose directories, and extract only to another disk or network share.
10. Validate representative files across ages and formats with full reads, magic, expected size,
    application tests, and destination-side hashes.
11. Save failure manifests and distinguish failed placeholders from genuine empty files.
12. Preserve case artifacts, sync the destination, stop jobs, and detach NBD/loop/MD before disk
    removal.

## Use FNOS and UFS evidence correctly

Use FNOS/UFS inventories to learn expected paths, names, sizes, and priorities. Do not infer
physical extent mappings or valid file content from names and displayed sizes alone. If UFS can
export physical runs, preserve them as evidence and validate each mapping against unrelated files.

## Report progress honestly

Report elapsed time, source read speed, target growth, file count, format-validated samples,
data-copy failures, metadata-only failures, genuine empty files, and destination free space.
Avoid percentages until the selected subtree total is known.
