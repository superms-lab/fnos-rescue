# Architecture

FNOS Rescue separates universal recovery safety from filesystem-specific recovery logic.

```text
CLI / local Web UI / Codex Skill
              |
       recovery state machine
              |
  device safety + cases + validation
              |
 filesystem plugins and native helpers
              |
 Linux block devices / images / QCOW2 overlays
```

## Core responsibilities

- identify devices by serial and topology;
- enforce read-only source layers;
- reject destinations on the source device tree;
- persist recovery state and artifacts;
- run long jobs independently of a terminal;
- report elapsed time, read speed, destination growth, and failures;
- validate complete file content rather than names and sizes alone.

## Plugin interface

Filesystem plugins implement these conceptual operations:

```text
probe -> diagnose -> list -> extract -> verify -> teardown
```

The initial plugin targets FNOS Basic single-disk Btrfs. ext4, NTFS, ZFS, XFS, and FAT/exFAT
will use separate plugins because their metadata and recovery models are not interchangeable.

## Native helper boundary

Python orchestrates the workflow. C is used for sequential block scanning where Python would add
avoidable overhead. Existing filesystem projects are invoked as external commands so their
licensing and failure boundaries remain explicit.

## Artifacts

Every disk receives a case directory containing device facts, superblock evidence, scan logs,
mapping caches, inventories, validation samples, recovery logs, and failure manifests. Passwords
and private paths must be redacted before sharing a case.
