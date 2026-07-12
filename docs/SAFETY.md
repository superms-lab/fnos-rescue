# Safety model

## Threat model

The most serious failure is writing to the only source disk. Other critical failures include
selecting the wrong physical disk after a reboot, restoring onto the source, trusting corrupt
metadata, exposing credentials, and calling zero-byte placeholders successful files.

## Required invariants

1. Identify the source with a stable serial and capacity.
2. Protect every source layer: disk, partition, MD/LVM, and loop.
3. Verify `RO=1` after protection.
4. Keep all reconstructed metadata inside a disposable image or QCOW2 overlay.
5. Use a distinct destination filesystem with enough free space.
6. Preserve logs and persistent scan caches before changing strategies.
7. Validate complete files at the destination.
8. Stop all jobs and detach NBD, loop, and MD layers before disk removal.

## Commands prohibited on a source

- filesystem formatting;
- `mdadm --create`;
- read-write mounting;
- `btrfs check --repair`;
- `btrfs rescue zero-log`;
- `btrfs rescue fix-device-size`;
- `xfs_repair` without `-n`;
- `e2fsck` without `-n`;
- TestDisk writes;
- ZFS rewind or import without read-only safeguards.

Some of these commands can be useful on a verified clone. They do not belong in the default
source-disk workflow.

## Physical errors

When the kernel reports read errors, resets, timeouts, or media errors, stop metadata exploration
and image the device with GNU ddrescue and a persistent mapfile. Repeated random scanning can make
a failing device worse.
