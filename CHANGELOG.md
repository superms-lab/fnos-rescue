# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and Semantic
Versioning.

## [Unreleased]

## [0.1.2] - 2026-07-13

### Added

- Add private Web access tokens for all device, case, job, inventory, and recovery APIs while
  retaining loopback-only listeners and Host/Origin checks.
- Add case/source/tool/hash provenance manifests for Chunk Cache artifacts and root candidate
  manifests carrying FSID, owner, generation, level, and physical-copy evidence.
- Add structural validators for ZIP/Office, gzip, tar, PNG, JPEG, GIF, PDF, SQLite, JSON, XML,
  text, and media files, with explicit validated, genuine-empty, unvalidated, and invalid states.
- Add a disposable Linux Btrfs-to-separate-ext4 end-to-end gate that proves the source image stays
  byte-identical, plus large-output, ENOSPC, restart, cache-corruption, and special-name tests.

### Fixed

- Traverse the complete partition/MD/LVM/loop holder/slave graph by kernel identity before source
  operations, and reject unknown or physically overlapping local destinations.
- Require case-owned QCOW2/NBD state, current process identity, overlay inode, backing-file match,
  and read-only backing before any metadata-writing helper opens a device.
- Validate forced historical tree blocks inside the private Btrfs tool before use, including FSID,
  bytenr, owner, generation, and level, and open devices read-only for salvage operations.
- Bound Chunk Cache record and stripe counts, reject truncation and trailing data, and fsync caches,
  inventories, and extracted files before reporting success.
- Encode inventory paths as relative Base64 byte identities so tabs, newlines, Unicode, and invalid
  UTF-8 cannot corrupt TSV parsing; resume batch extraction by stable rootid/inode/path identity.
- Stream long-running child stdout/stderr directly to durable job logs, cap returned diagnostics,
  terminate process groups, and recover stale workers after reboot.
- Replace path-based copying with descriptor-relative `openat`/`O_NOFOLLOW` traversal, atomic
  replacement, fsync, and final destination reread; preserve retry safety after interruption.
- Make verification include empty files and prevent completed-with-errors jobs or any failure
  manifest from being reported ready.

### Security

- Sandbox fnOS and Live Web services with read-only system paths and narrowly scoped write paths.
- Reject arbitrary Web filesystem paths, recovery binaries, cache files, devices, non-loopback
  listeners, and missing/invalid access tokens.
- Keep all physical source layers read-only and confine metadata reconstruction to proven,
  case-owned QCOW2 overlays.

### Validation

- Passed 91 automated Python tests on macOS before publication, the React production build, npm
  high-severity audit, secret scan, Live profile validation, Python/Shell syntax checks, and clean
  diff checks.
- Linux private-tool compilation, Debian/fnOS packaging, disposable Btrfs E2E, fnOS lifecycle,
  and BIOS/UEFI Live ISO boot are required CI/release gates for the v0.1.2 prerelease.

## [0.1.1] - 2026-07-13

### Added

- Package the advanced read-only Btrfs root scanner and private historical-tree helper in Debian,
  fnOS, Live ISO, and release artifacts using fixed trusted paths.
- Complete the guided Web recovery flow for cases, device protection, destination validation,
  allowlisted Btrfs jobs, progress control, and recovery reports.
- Add a loopback-only, systemd-sandboxed fnOS Web service with install, upgrade rollback, and
  uninstall lifecycle support.
- Add Windows, macOS, Debian/Ubuntu, fnOS, and Live ISO entrypoints plus BIOS/UEFI boot diagnostics.

### Fixed

- Pin Debian mirrors explicitly when building a Bookworm Live image on Ubuntu CI runners.
- Remove all hard-coded Web demo devices and show explicit empty/error states when no real local
  service or block device is available.
- Replace the broken BIOS COM32 menu dependency with a deterministic ISOLINUX entry and reject
  unresolved bootloader placeholders in release CI.
- Load split OVMF CODE and VARS images through pflash for reproducible UEFI validation.
- Clean release build directories and Python bytecode before packaging so stale assets and
  `__pycache__` files cannot leak into archives.

### Security

- Restrict the fnOS root helper to fixed diagnostic/read-only operations and reject shell,
  interpreter, arbitrary job, and caller-supplied executable paths.
- Keep the Web service bound to `127.0.0.1`, require mutation session tokens, validate trusted
  recovery-tool paths, and preserve source/destination and symlink escape protections.

### Validation

- Passed 64 automated tests on Python 3.11, 3.12, and 3.13, the Web production build, npm audit,
  secret scanning, recovery-tool compilation, Debian/fnOS packaging, and artifact verification.
- Exercised fnOS archive installation, loopback-only Web health, systemd sandbox properties,
  helper allow/deny behavior, upgrade rollback, and final uninstall on a disposable systemd runner.
- Booted the generated Live ISO in headless QEMU using both legacy BIOS and UEFI and required the
  Web service, kiosk, root scanner, and private Btrfs helper to report ready in each mode.

## [0.1.0] - 2026-07-12

### Added

- Durable recovery jobs with atomic state files, resumable completed-step tracking, JSONL
  progress events, and append-only failure manifests.
- `job-create`, `job-list`, and `job-show` CLI commands.
- Foreground and detached-background `verify` job execution with idempotent resume, worker PID,
  logs, and atomic result files via `job-run`.
- Cooperative pause, resume, and cancel requests via `job-control`.
- Resumable selected-path copy jobs with traversal protection, preserved directory layout, and
  source/destination SHA-256 validation.
- Linux destination inspection for local, SMB/CIFS, and NFS mounts, including read-only,
  writability, and required-capacity gates enforced by copy jobs.
- `doctor` platform and dependency diagnostics for the Linux recovery runtime.
- Debian/Ubuntu package builder and CI/release validation for `.deb` artifacts.
- Durable read-only Btrfs superblock-probe and historical-root-scan jobs with private evidence
  artifacts, FSID validation, optional scan ranges, and background execution support.
- Durable private-Btrfs jobs for reusable chunk-cache generation, historical filesystem-tree
  inventory, and validated single-inode extraction into isolated case artifacts.
- Safe batch inode extraction, interruptible native processes, case-level validation reports,
  QCOW2/NBD lifecycle and cleanup jobs, plus read-only ext4 and NTFS diagnostics.
- Native fnOS environment detection, dry-run service quiesce planning, architecture-labelled
  application archives, upgrade rollback, clean uninstall, and a fixed-command root helper.
- Shared local React recovery console with responsive desktop/mobile layouts.
- Guided case creation, destination validation, allowlisted background jobs, and job controls.
- Debian Live ISO profile and CI artifact pipeline, plus Windows/macOS recovery entrypoint guides.
- CycloneDX SBOM, SHA-256 release manifests, npm audit, secret scanning, and release preflight.

### Security

- Require physical source-device checks before copy jobs and reject same-disk destinations.
- Reject path traversal and source/destination symlinks in both copy implementations.
- Add per-job worker locks, strict job ID validation, private case permissions, atomic destination
  replacement, source-change detection, and retryable per-file failures.
- Require a random per-process session token on every Web mutation and apply CSP, anti-framing,
  no-referrer, and content-type security headers to API and static responses.

### Validation

- Validated on Ubuntu 26.04 with a disposable read-only Btrfs loop image, physical same-disk
  rejection, dependency diagnostics, and full `.deb` install/run/remove lifecycle.
- Validated the native archive on Debian 12-based fnOS x86_64 with install, detection, dependency
  checks, helper allow/deny behavior, uninstall, service-state preservation, and no residue.
- Validated 54 automated tests, the Web production build, zero known npm vulnerabilities,
  sensitive-data scanning, package construction, and release metadata generation.

[Unreleased]: https://github.com/superms-lab/fnos-rescue/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/superms-lab/fnos-rescue/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/superms-lab/fnos-rescue/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/superms-lab/fnos-rescue/releases/tag/v0.1.0
