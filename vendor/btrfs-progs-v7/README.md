# Modified btrfs-progs v7 sources

These files replace the matching files in btrfs-progs v7.0 at upstream commit
`9c5987432906daebde23f9703c0f6f90c35fa9da` to build a
private recovery binary. They add case-tested persistent chunk caches, forced historical roots,
path listing, targeted extraction, and ignore-error subtree recovery.

They are derivative works of btrfs-progs and remain GPL-2.0-only. Do not install the resulting
binary over the system `btrfs` command. Build it in an isolated directory and use its absolute
path only against a source-protected image or QCOW2 overlay.

`scripts/build-recovery-tools.sh` checks out that exact commit and installs the private binary as
`fnos-rescue-btrfs`; it must never replace the system `btrfs` executable.
