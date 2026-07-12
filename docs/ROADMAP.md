# Roadmap

## 0.1.x: FNOS/Btrfs safety foundation

- harden Linux device inspection and recursive read-only protection;
- stabilize case artifacts and schemas;
- package the proven FNOS root scanner and QCOW2 helpers;
- add generated Btrfs corruption fixtures;
- automate persistent chunk-cache and selected-directory extraction jobs.

Current P1 checkpoint: durable job state, resumable step tracking, JSONL progress, failure
manifests, detached workers, cooperative pause/cancel controls, verification, and validated
selected-path copy execution are implemented. Local, SMB/CIFS, and NFS destination identification
plus capacity/write-readiness gates are also implemented; automated mount helpers and package
installation remain. Linux dependency diagnostics and Debian/Ubuntu package construction are
implemented and validated on Ubuntu 26.04, including package install/remove, dependency checks,
read-only loop inspection, Btrfs superblock probing, and same-physical-disk rejection.
Stage 1 Linux core now also includes durable root scanning, chunk-cache reuse, filesystem-tree
listing, single and batch inode extraction, interruptible native jobs, QCOW2/NBD lifecycle cleanup,
case reports, and read-only ext4/NTFS diagnostics.

## 0.2.x: guided recovery

- resumable background jobs with JSONL progress;
- local Web UI for disk and directory selection;
- failure manifests and historical-root retries;
- Live ISO build pipeline;
- destination-side validation reports.

## 0.3.x: portable environment

- signed Live ISO/USB image;
- Windows WSL2 helper and pass-through diagnostics;
- macOS VM/pass-through documentation;
- SMB/NFS destination wizard.

## 0.4.x and later: separate filesystem plugins

- ext4: alternate superblocks, e2image, inode/extent extraction;
- NTFS: boot sector, MFT/MFTMirr, TestDisk-assisted extraction;
- ZFS: labels, uberblocks, read-only import, historical txg inspection;
- XFS and FAT/exFAT diagnostics and extraction;
- APFS research plugin without stable-support claims.

Each plugin is labeled `experimental`, `beta`, or `stable` independently.
