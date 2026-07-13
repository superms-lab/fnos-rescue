# FNOS Basic-disk Btrfs recovery runbook

This runbook describes the evidence-driven path used by FNOS Rescue. Replace placeholders and
save every command output in a case directory.

## 1. Freeze and identify

```bash
lsblk -o NAME,PATH,SIZE,RO,TYPE,FSTYPE,MODEL,SERIAL,UUID
sudo fnos-rescue inspect /dev/DEVICE
sudo fnos-rescue protect /dev/DEVICE --confirm-serial SERIAL --dry-run
sudo fnos-rescue protect /dev/DEVICE --confirm-serial SERIAL
```

If FNOS left mdadm metadata, inspect the member and assemble it read-only. Record the mdadm data
offset separately from the Btrfs offset.

```bash
sudo mdadm --examine /dev/PARTITION
sudo mdadm --assemble --readonly --run /dev/md/RECOVERY /dev/PARTITION
sudo losetup --find --show --read-only --offset BTRFS_OFFSET /dev/md/RECOVERY
```

Verify every displayed layer reports read-only before continuing.

## 2. Inspect all Btrfs super mirrors

```bash
sudo fnos-rescue btrfs-probe /dev/READ_ONLY_LOOP
```

Primary and secondary mirrors may be blank while the third mirror at 256 GiB still contains a
valid FSID, generation, root-tree address, device UUID, and system chunk array.

## 3. Find coherent roots

Compile and run the bundled scanner against the read-only Btrfs view:

```bash
./scripts/build-recovery-tools.sh
sudo ./scan-btrfs-roots /dev/READ_ONLY_LOOP FSID START_GIB END_GIB \
  > scans/root-scan.log 2>&1
```

Prefer candidates that match the superblock generation and have byte-identical DUP copies.
Record physical address, logical bytenr, generation, owner, level, and checksum evidence.

Do not hardcode the FNOS mapping pattern. A candidate such as a 1 GiB metadata chunk with an
8 MiB displacement is acceptable only after FSID, bytenr, owner, generation, checksum, and both
DUP copies validate.

## 4. Create a disposable overlay

```bash
fnos-rescue job-create CASE overlay-create \
  --parameters '{"backing_device":"/dev/READ_ONLY_LOOP"}'
fnos-rescue job-run CASE OVERLAY-CREATE-JOB
sudo modprobe nbd max_part=8
fnos-rescue job-create CASE overlay-connect \
  --parameters '{"overlay":"CASE/jobs/OVERLAY-CREATE-JOB/recovery-overlay.qcow2","nbd_device":"/dev/nbd0"}'
fnos-rescue job-run CASE OVERLAY-CONNECT-JOB
sudo python helpers/set_btrfs_historical_root.py \
  /dev/nbd0 ROOT_BYTENR GENERATION ROOT_LEVEL \
  --overlay-state CASE/jobs/OVERLAY-CONNECT-JOB/overlay-state.json
```

The backing source must remain read-only. `/dev/nbd0` is the only writable experimental view. The
helper refuses raw disks and requires a current, private state file created by the case-owned
overlay connection job; a confirmation flag by itself is not accepted as proof.

## 5. Preserve chunk mappings

The modified btrfs-progs v7 sources under `vendor/btrfs-progs-v7/` support persistent chunk
caches, forced historical roots, path listing, targeted extraction, and ignore-error subtree
recovery. Build a private binary; never install it over the system `btrfs` binary.

```bash
scripts/build-private-btrfs.sh /path/to/btrfs-progs-v7
```

Run one chunk scan and save the cache. Do not repeat a full-device scan when a reusable cache
already exists.

## 6. List, select, recover, validate

Use the cache and a coherent filesystem root to list paths. Recover selected directories to a
different disk or network share. Validate representative files across ages and formats with full
reads, magic checks, archive tests, media parsers, expected sizes, and destination-side hashes.

Do not reuse a loose cache file or type a root address from memory. The cache manifest must match
the current case source identity, recovery layer and exact private-tool SHA-256. The selected root
must come from the same case's `root-candidates.json`; FSID, owner, generation and level are passed
to and rechecked inside the private C tool before the tree block is used. Cache readers reject
unbounded record/stripe counts, truncated records and trailing bytes.

Results explicitly distinguish `validated`, `genuine_empty`, `unvalidated`, and `invalid` content.
Keep every failed or unvalidated artifact until its manifest has been reviewed. A plausible
filename, size, or self-computed hash is inventory evidence, not proof of valid content.

## 7. Finish safely

Copy logs, caches, inventories, and overlays to the case artifacts. Then:

```bash
sync
sudo qemu-nbd --disconnect /dev/nbd0
sudo losetup -d /dev/READ_ONLY_LOOP
sudo mdadm --stop /dev/md/RECOVERY
```

Confirm the partition has no holders before shutting down and removing the disk.
