# FNOS Rescue

> Read-only-first recovery toolkit for FNOS Basic-disk Btrfs volumes.

[![CI](https://github.com/superms-lab/fnos-rescue/actions/workflows/ci.yml/badge.svg)](https://github.com/superms-lab/fnos-rescue/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/superms-lab/fnos-rescue?include_prereleases)](https://github.com/superms-lab/fnos-rescue/releases)

[中文说明](README.zh-CN.md)

FNOS makes **Remove** and **Unmount** easy to confuse. When a Basic disk is removed from a
storage pool, the files may still exist while partition, RAID, Btrfs superblock, chunk-tree, or
root-tree metadata can no longer be opened normally. FNOS Rescue turns the recovery process into
an auditable, repeatable workflow instead of a collection of dangerous one-off commands.

## Current status

`v0.1.2` is an alpha, Linux-first prerelease extracted from successful real-world FNOS Basic-disk
Btrfs recoveries. It provides:

- device inspection with stable serial reporting;
- serial-confirmed, recursive read-only protection;
- source/destination separation checks;
- durable JSON recovery cases;
- all-mirror Btrfs superblock inspection;
- fast read-only Btrfs root scanning helpers;
- QCOW2-only historical-root and synthetic-metadata helpers;
- representative file hashing and type validation;
- a loopback-only guided Web recovery console and sandboxed fnOS service;
- a BIOS/UEFI-validated Debian Live ISO for Windows, macOS, Linux, and NAS hosts;
- a Codex recovery skill and detailed safety runbook.

This is not yet a one-click recovery application. Low-level recovery can destroy the only copy of
your data when used incorrectly. If a drive has physical read errors, image it with GNU ddrescue
and a mapfile before filesystem work.

## Non-negotiable safety rules

1. Never restore onto the source disk.
2. Keep the physical disk, partition, MD/LVM, and loop layers read-only.
3. Write reconstructed metadata only to a disposable image or QCOW2 overlay.
4. Never run repair, formatting, RAID creation, or read-write mounting on the source.
5. Validate file content; a plausible name and size do not prove successful recovery.

## Install for development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
fnos-rescue --version
```

Raw block-device operations require Linux and native tools such as `lsblk`, `blockdev`, `mdadm`,
`btrfs-progs`, `qemu-img`, and `qemu-nbd`.

## Native fnOS package

Build the architecture-labelled fnOS archive with `./scripts/build-fnos-package.sh`. It installs
under `/var/apps/fnos-rescue`, supports upgrade rollback and clean uninstall, and includes a
fixed-command root helper that refuses arbitrary shell execution. `fnos-quiesce-plan` is dry-run
only and never stops active fnOS services by itself.

The fnOS Web console is loopback-only and requires a private access token. Display it locally with
`sudo /var/apps/fnos-rescue/bin/fnos-rescue-web-url`; for another computer, use the printed SSH
port-forward command and enter the token in the browser. Direct LAN listening is intentionally
refused.

Check the complete runtime before touching a device:

```bash
fnos-rescue doctor
```

On Debian/Ubuntu, build the native package with `./scripts/build-deb.sh`. The resulting `.deb`
declares `util-linux`, `file`, `btrfs-progs`, `mdadm`, and `qemu-utils` as system dependencies.

## Safe first commands

```bash
sudo fnos-rescue inspect /dev/nvme0n1
sudo fnos-rescue protect /dev/nvme0n1 \
  --confirm-serial 'SERIAL-FROM-INSPECT' --dry-run
sudo fnos-rescue protect /dev/nvme0n1 \
  --confirm-serial 'SERIAL-FROM-INSPECT'
sudo fnos-rescue btrfs-probe /dev/loop16
fnos-rescue verify /mnt/recovery --limit 10
```

Durable jobs keep resumable state, JSONL progress, and append-only failure manifests inside a
recovery case:

```bash
fnos-rescue job-create ./case-001 copy --parameters \
  '{"source_device":"/dev/sda","source_root":"/mnt/recovery-view","destination":"/mnt/recovery","paths":["Photos/2025"]}'
fnos-rescue job-list ./case-001
fnos-rescue job-show ./case-001 job-0123456789ab
fnos-rescue job-run ./case-001 job-0123456789ab --background
fnos-rescue job-control ./case-001 job-0123456789ab pause
fnos-rescue job-control ./case-001 job-0123456789ab resume
```

The `verify` executor is available during P1. Creating a job records intent; `job-run` is the
explicit action that starts or resumes supported work. Background workers write `worker.pid`,
`worker.log`, `progress.jsonl`, and atomic result state inside the job directory.

Validated directory copying uses an explicit source root, destination, and relative path list:

```bash
fnos-rescue job-create ./case-001 copy --parameters \
  '{"source_device":"/dev/sda","source_root":"/mnt/recovery-view","destination":"/mnt/output","paths":["Photos/2025"]}'
```

The copy executor requires the original physical `source_device`, rechecks the case serial,
capacity, complete kernel device graph, and read-only state, rejects same-disk destinations,
absolute selections, path traversal, and symlinks, preserves relative paths, and compares
source/destination SHA-256 before marking each file complete.

On Linux, inspect a mounted local disk, SMB/CIFS share, or NFS export before creating a copy job:

```bash
fnos-rescue destination-inspect /mnt/output --required-bytes 10737418240
```

The command reports the backing source, mountpoint, filesystem class, read-only state, write
readiness, and available capacity. Copy jobs run the same check automatically before writing.

Btrfs evidence collection can also run as durable jobs:

```bash
fnos-rescue job-create ./case-001 btrfs-probe \
  --parameters '{"device":"/dev/loop16"}'
fnos-rescue job-create ./case-001 btrfs-root-scan --parameters \
  '{"device":"/dev/loop16","fsid":"11111111-2222-3333-4444-555555555555"}'
fnos-rescue job-run ./case-001 job-0123456789ab --background
```

Both jobs require the case source or a read-only partition/MD/LVM/loop layer proven by the kernel
device graph to belong to that source. They collect evidence only and never mount, repair, or
rewrite a superblock.

The private Btrfs v7 helper can persist a reusable chunk cache, list a historical filesystem tree,
and extract one known inode into the private job directory:

```bash
fnos-rescue job-create ./case-001 btrfs-chunk-cache --parameters \
  '{"device":"/dev/loop16","fsid":"11111111-2222-3333-4444-555555555555"}'
fnos-rescue job-create ./case-001 btrfs-list --parameters \
  '{"device":"/dev/loop16","chunk_cache":"./case-001/jobs/JOB/chunk-mappings.cache","filesystem_root":123456}'
fnos-rescue job-create ./case-001 btrfs-extract-inode --parameters \
  '{"device":"/dev/loop16","chunk_cache":"./case-001/jobs/JOB/chunk-mappings.cache","filesystem_root":123456,"rootid":257,"inode":9001,"expected_size":4096,"expected_sha256":"TRUSTED_INVENTORY_SHA256"}'
```

The selected filesystem or subvolume root must exist in the same case's completed
`root-candidates.json`; its FSID, owner, generation and level are checked again by both the
orchestrator and private C tool. A chunk cache is accepted only with its case/source/tool SHA-256
provenance manifest. Extraction first lands inside the private case job directory. Known archives,
documents, images, databases, text and media are structurally parsed; an opaque format requires a
trusted inventory SHA-256, otherwise it is retained but reported as unvalidated. Moving validated content to a final
destination remains a separate `copy` job so physical same-disk checks cannot be bypassed.

Read [the FNOS Btrfs runbook](docs/FNOS-BTRFS.md) before attempting recovery.

## Why a Linux core?

Windows can attach some physical disks to WSL2 and macOS can pass external storage to a VM, but
the reliable recovery primitives used here are Linux block-device, mdadm, Btrfs, NBD, and QEMU
interfaces. The project roadmap therefore targets one Linux engine, a bootable Live environment,
and a browser UI instead of three divergent recovery engines.

## Roadmap

- `0.1.x`: harden FNOS Basic single-disk Btrfs diagnostics and recovery artifacts.
- `0.2.x`: guided extraction jobs, resumable state, failure manifests, and a local Web UI.
- `0.3.x`: bootable Live image for Windows/macOS users.
- `0.4.x+`: separate ext4, NTFS, ZFS, XFS, and FAT/exFAT plugins.

See [ROADMAP.md](docs/ROADMAP.md) and [VERSIONING.md](docs/VERSIONING.md).

## Licensing

The orchestrator is Apache-2.0. Modified btrfs-progs source files under
`vendor/btrfs-progs-v7/` remain GPL-2.0-only and are intentionally kept separate. External tools
retain their own licenses.

## Privacy

Do not upload raw user disks, credentials, private filenames, or unredacted recovery logs. Use
generated fixtures and the recovery-case issue template.
