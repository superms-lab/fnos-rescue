# FNOS Rescue

> Read-only-first recovery toolkit for FNOS Basic-disk Btrfs volumes.

[![CI](https://github.com/supermslab/fnos-rescue/actions/workflows/ci.yml/badge.svg)](https://github.com/supermslab/fnos-rescue/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/supermslab/fnos-rescue?include_prereleases)](https://github.com/supermslab/fnos-rescue/releases)

[中文说明](README.zh-CN.md)

FNOS makes **Remove** and **Unmount** easy to confuse. When a Basic disk is removed from a
storage pool, the files may still exist while partition, RAID, Btrfs superblock, chunk-tree, or
root-tree metadata can no longer be opened normally. FNOS Rescue turns the recovery process into
an auditable, repeatable workflow instead of a collection of dangerous one-off commands.

## Current status

`v0.1.0` is an alpha, Linux-first foundation extracted from successful real-world FNOS Basic-disk
Btrfs recoveries. It provides:

- device inspection with stable serial reporting;
- serial-confirmed, recursive read-only protection;
- source/destination separation checks;
- durable JSON recovery cases;
- all-mirror Btrfs superblock inspection;
- fast read-only Btrfs root scanning helpers;
- QCOW2-only historical-root and synthetic-metadata helpers;
- representative file hashing and type validation;
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
