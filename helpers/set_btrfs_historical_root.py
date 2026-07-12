#!/usr/bin/env python3
"""Point Btrfs superblock mirrors at a verified historical tree root.

This is intended only for a disposable copy-on-write recovery overlay.
"""

import os
import struct
import sys

from crc32c_compat import crc32c


SUPER_SIZE = 4096
SUPER_OFFSETS = (64 << 10, 64 << 20, 256 << 30)
MAGIC = b"_BHRfS_M"


def checksum(block: bytes) -> bytes:
    return struct.pack("<I", crc32c(block[32:]))


def main() -> int:
    if len(sys.argv) not in (4, 5):
        print(
            f"usage: {sys.argv[0]} DEVICE ROOT_BYTENR GENERATION [ROOT_LEVEL]",
            file=sys.stderr,
        )
        return 2

    device = sys.argv[1]
    root = int(sys.argv[2], 0)
    generation = int(sys.argv[3], 0)
    root_level = int(sys.argv[4], 0) if len(sys.argv) == 5 else 1
    if root_level < 0 or root_level > 8:
        raise ValueError("ROOT_LEVEL must be between 0 and 8")
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
