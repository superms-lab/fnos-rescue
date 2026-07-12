# Modified btrfs-progs v7 sources

These files replace the matching files in a compatible btrfs-progs v7 source tree to build a
private recovery binary. They add case-tested persistent chunk caches, forced historical roots,
path listing, targeted extraction, and ignore-error subtree recovery.

They are derivative works of btrfs-progs and remain GPL-2.0-only. Do not install the resulting
binary over the system `btrfs` command. Build it in an isolated directory and use its absolute
path only against a source-protected image or QCOW2 overlay.

The first public release intentionally keeps these sources separate from the Apache-2.0 Python
orchestrator. A future release should publish minimal patch files against an exact upstream tag
in addition to the complete replacement files.
