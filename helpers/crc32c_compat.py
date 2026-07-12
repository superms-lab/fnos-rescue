"""Dependency-free CRC32C (Castagnoli) for offline recovery helpers."""

from __future__ import annotations


POLYNOMIAL = 0x82F63B78


def _make_table() -> tuple[int, ...]:
    table = []
    for value in range(256):
        checksum = value
        for _ in range(8):
            checksum = (checksum >> 1) ^ (POLYNOMIAL if checksum & 1 else 0)
        table.append(checksum & 0xFFFFFFFF)
    return tuple(table)


TABLE = _make_table()


def crc32c(data: bytes | bytearray | memoryview, initial: int = 0) -> int:
    checksum = initial ^ 0xFFFFFFFF
    for value in memoryview(data).cast("B"):
        checksum = TABLE[(checksum ^ value) & 0xFF] ^ (checksum >> 8)
    return (checksum ^ 0xFFFFFFFF) & 0xFFFFFFFF
