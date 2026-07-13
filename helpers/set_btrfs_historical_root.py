#!/usr/bin/env python3
"""Point Btrfs superblock mirrors at a verified historical tree root.

This is intended only for a disposable copy-on-write recovery overlay.
"""

import argparse
import os
import struct

from crc32c_compat import crc32c
from overlay_safety import require_connected_case_overlay


SUPER_SIZE = 4096
SUPER_OFFSETS = (64 << 10, 64 << 20, 256 << 30)
MAGIC = b"_BHRfS_M"


def checksum(block: bytes) -> bytes:
    return struct.pack("<I", crc32c(block[32:]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("device")
    parser.add_argument("root_bytenr", type=lambda value: int(value, 0))
    parser.add_argument("generation", type=lambda value: int(value, 0))
    parser.add_argument("root_level", nargs="?", type=lambda value: int(value, 0), default=1)
    parser.add_argument("--overlay-state", required=True)
    args = parser.parse_args()
    device = args.device
    root = args.root_bytenr
    generation = args.generation
    root_level = args.root_level
    if root_level < 0 or root_level > 8:
        raise ValueError("ROOT_LEVEL must be between 0 and 8")
    require_connected_case_overlay(device, args.overlay_state)
    fd = os.open(device, os.O_RDWR | os.O_CLOEXEC)
    try:
        source = bytearray(os.pread(fd, SUPER_SIZE, SUPER_OFFSETS[2]))
        if len(source) != SUPER_SIZE:
            raise RuntimeError("could not read the third superblock mirror")
        if source[64:72] != MAGIC:
            raise RuntimeError("third mirror has no Btrfs magic")
        if source[:4] != checksum(source):
            raise RuntimeError("third mirror checksum is invalid")

        for offset in SUPER_OFFSETS:
            block = bytearray(source)
            block[:32] = b"\0" * 32
            struct.pack_into("<Q", block, 48, offset)       # bytenr
            struct.pack_into("<Q", block, 72, generation)   # generation
            struct.pack_into("<Q", block, 80, root)         # tree root
            block[198] = root_level                          # root level
            block[:4] = checksum(block)
            written = os.pwrite(fd, block, offset)
            if written != SUPER_SIZE:
                raise RuntimeError(f"short write at {offset}: {written}")
            print(
                f"wrote mirror={offset} root={root} generation={generation} "
                f"level={root_level} "
                f"checksum={block[:4].hex()}"
            )
        os.fsync(fd)
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
