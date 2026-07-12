#!/usr/bin/env python3
"""Build a minimal Btrfs chunk tree from a persistent recovery cache.

This writes tree blocks and superblocks. Use only on a disposable QCOW overlay.
"""

from __future__ import annotations

import argparse
import os
import struct
import uuid

from crc32c_compat import crc32c


NODE_SIZE = 16 * 1024
SUPER_SIZE = 4096
SUPER_OFFSETS = (64 << 10, 64 << 20, 256 << 30)
HEADER_SIZE = 101
ITEM_SIZE = 25
NODEPTR_SIZE = 33
CHUNK_OBJECTID = 256
CHUNK_ITEM_KEY = 228
DEV_ITEM_KEY = 216
CHUNK_TREE_OWNER = 3
HEADER_FLAG_WRITTEN = 1


def checksum(block: bytearray) -> None:
    block[:32] = b"\0" * 32
    struct.pack_into("<I", block, 0, crc32c(block[32:]))


def pack_key(objectid: int, key_type: int, offset: int) -> bytes:
    return struct.pack("<QBQ", objectid, key_type, offset)


def make_header(
    fsid: bytes,
    chunk_uuid: bytes,
    bytenr: int,
    generation: int,
    nritems: int,
    level: int,
    owner: int = CHUNK_TREE_OWNER,
) -> bytearray:
    block = bytearray(NODE_SIZE)
    block[32:48] = fsid
    struct.pack_into("<Q", block, 48, bytenr)
    struct.pack_into("<Q", block, 56, HEADER_FLAG_WRITTEN)
    block[64:80] = chunk_uuid
    struct.pack_into("<Q", block, 80, generation)
    struct.pack_into("<Q", block, 88, owner)
    struct.pack_into("<I", block, 96, nritems)
    block[100] = level
    return block


def read_cache(path: str) -> list[dict]:
    chunks: list[dict] = []
    with open(path, "rb") as handle:
        magic, version, count = struct.unpack("=8sII", handle.read(16))
        if magic != b"BTRCHNK1" or version != 1:
            raise RuntimeError("unsupported chunk cache")
        for _ in range(count):
            raw = handle.read(88)
            if len(raw) != 88:
                raise RuntimeError("short chunk cache record")
            kind = struct.unpack_from("=I", raw, 0)[0]
            num_stripes, sub_stripes = struct.unpack_from("=HH", raw, 4)
            generation, objectid = struct.unpack_from("=QQ", raw, 8)
            key_type = raw[24]
            offset, owner, length, flags, stripe_len = struct.unpack_from(
                "=QQQQQ", raw, 32
            )
            io_align, io_width, sector_size = struct.unpack_from("=III", raw, 72)
            stripes = []
            for _stripe in range(num_stripes):
                stripe_raw = handle.read(32)
                devid, physical = struct.unpack_from("=QQ", stripe_raw, 0)
                stripes.append((devid, physical, stripe_raw[16:32]))
            if kind not in (1, 2):
                continue
            chunks.append(
                dict(
                    generation=generation,
                    objectid=objectid,
                    key_type=key_type,
                    offset=offset,
                    owner=owner,
                    length=length,
                    flags=flags,
                    stripe_len=stripe_len,
                    num_stripes=num_stripes,
                    sub_stripes=sub_stripes,
                    io_align=io_align,
                    io_width=io_width,
                    sector_size=sector_size,
                    stripes=stripes,
                )
            )
    return chunks


def chunk_payload(chunk: dict) -> bytes:
    out = bytearray(48 + 32 * chunk["num_stripes"])
    struct.pack_into(
        "<QQQQIIIHH",
        out,
        0,
        chunk["length"],
        chunk["owner"],
        chunk["stripe_len"],
        chunk["flags"],
        chunk["io_align"],
        chunk["io_width"],
        chunk["sector_size"],
        chunk["num_stripes"],
        chunk["sub_stripes"],
    )
    for index, (devid, physical, dev_uuid) in enumerate(chunk["stripes"]):
        pos = 48 + index * 32
        struct.pack_into("<QQ", out, pos, devid, physical)
        out[pos + 16 : pos + 32] = dev_uuid
    return bytes(out)


def make_leaf(
    entries: list[dict], fsid: bytes, chunk_uuid: bytes, bytenr: int,
    generation: int, owner: int = CHUNK_TREE_OWNER
) -> bytearray:
    block = make_header(
        fsid, chunk_uuid, bytenr, generation, len(entries), 0, owner
    )
    data_end = NODE_SIZE
    for slot, entry in enumerate(entries):
        payload = entry.get("raw_payload") or chunk_payload(entry)
        data_end -= len(payload)
        item_pos = HEADER_SIZE + slot * ITEM_SIZE
        block[item_pos : item_pos + 17] = pack_key(
            entry["objectid"], entry["key_type"], entry["offset"]
        )
        struct.pack_into(
            "<II", block, item_pos + 17, data_end - HEADER_SIZE, len(payload)
        )
        block[data_end : data_end + len(payload)] = payload
    if HEADER_SIZE + len(entries) * ITEM_SIZE > data_end:
        raise RuntimeError("leaf overflow")
    checksum(block)
    return block


def make_root(
    leaves: list[tuple[int, dict]],
    fsid: bytes,
    chunk_uuid: bytes,
    bytenr: int,
    generation: int,
) -> bytearray:
    block = make_header(fsid, chunk_uuid, bytenr, generation, len(leaves), 1)
    for slot, (leaf_bytenr, first_entry) in enumerate(leaves):
        pos = HEADER_SIZE + slot * NODEPTR_SIZE
        block[pos : pos + 17] = pack_key(
            first_entry["objectid"], first_entry["key_type"], first_entry["offset"]
        )
        struct.pack_into("<QQ", block, pos + 17, leaf_bytenr, generation)
    checksum(block)
    return block


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("device")
    parser.add_argument("cache")
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--tree-root", type=int, required=True)
    parser.add_argument("--tree-root-level", type=int, default=1)
    parser.add_argument("--chunk-root", type=int, required=True)
    parser.add_argument("--system-logical", type=int, required=True)
    parser.add_argument("--system-length", type=int, default=8 << 20)
    parser.add_argument("--system-physical", type=int, action="append", required=True)
    parser.add_argument("--metadata-logical", type=int)
    parser.add_argument("--metadata-length", type=int, default=1 << 30)
    parser.add_argument("--metadata-physical", type=int, action="append")
    parser.add_argument("--dev-stats-logical", type=int)
    parser.add_argument("--dev-stats-generation", type=int, default=3453)
    parser.add_argument(
        "--empty-tree", action="append",
        help="logical,generation,owner; write an empty level-0 tree on overlay",
    )
    parser.add_argument(
        "--clone-leaf", action="append",
        help="source_logical,target_logical,generation,owner",
    )
    parser.add_argument("--chunk-uuid", required=True)
    parser.add_argument("--confirm-overlay", action="store_true", required=True)
    args = parser.parse_args()

    chunks = read_cache(args.cache)
    if not chunks:
        raise RuntimeError("cache contains no recoverable chunks")
    read_fd = os.open(args.device, os.O_RDONLY | os.O_CLOEXEC)
    first_super = os.pread(read_fd, SUPER_SIZE, SUPER_OFFSETS[0])
    os.close(read_fd)
    fsid = first_super[32:48]
    if len(fsid) != 16:
        raise RuntimeError("cannot read FSID")
    chunk_uuid = uuid.UUID(args.chunk_uuid).bytes
    dev_uuid = chunks[0]["stripes"][0][2]

    chunks = [
        chunk
        for chunk in chunks
        if not (
            chunk["offset"] < args.system_logical + args.system_length
            and chunk["offset"] + chunk["length"] > args.system_logical
        )
    ]
    system_chunk = dict(
        generation=args.generation,
        objectid=CHUNK_OBJECTID,
        key_type=CHUNK_ITEM_KEY,
        offset=args.system_logical,
        owner=2,
        length=args.system_length,
        flags=34,  # SYSTEM | DUP
        stripe_len=64 << 10,
        num_stripes=len(args.system_physical),
        sub_stripes=1,
        io_align=64 << 10,
        io_width=64 << 10,
        sector_size=4096,
        stripes=[(1, physical, dev_uuid) for physical in args.system_physical],
    )
    chunks.append(system_chunk)
    if args.metadata_logical is not None:
        if not args.metadata_physical:
            raise RuntimeError("--metadata-physical is required")
        chunks = [
            chunk
            for chunk in chunks
            if not (
                chunk.get("offset", -1) < args.metadata_logical + args.metadata_length
                and chunk.get("offset", -1) + chunk.get("length", 0)
                > args.metadata_logical
            )
        ]
        chunks.append(
            dict(
                generation=args.generation,
                objectid=CHUNK_OBJECTID,
                key_type=CHUNK_ITEM_KEY,
                offset=args.metadata_logical,
                owner=2,
                length=args.metadata_length,
                flags=36,  # METADATA | DUP
                stripe_len=64 << 10,
                num_stripes=len(args.metadata_physical),
                sub_stripes=1,
                io_align=64 << 10,
                io_width=64 << 10,
                sector_size=4096,
                stripes=[
                    (1, physical, dev_uuid)
                    for physical in args.metadata_physical
                ],
            )
        )
    chunks.append(
        dict(
            objectid=1,
            key_type=DEV_ITEM_KEY,
            offset=1,
            raw_payload=first_super[201:299],
        )
    )
    chunks.sort(key=lambda item: (item["objectid"], item["key_type"], item["offset"]))

    groups = [chunks[index : index + 100] for index in range(0, len(chunks), 100)]
    leaf_defs = []
    blocks: list[tuple[int, bytearray]] = []
    for index, entries in enumerate(groups, 1):
        logical = args.chunk_root + index * NODE_SIZE
        blocks.append(
            (logical, make_leaf(entries, fsid, chunk_uuid, logical, args.generation))
        )
        leaf_defs.append((logical, entries[0]))
    blocks.append(
        (
            args.chunk_root,
            make_root(leaf_defs, fsid, chunk_uuid, args.chunk_root, args.generation),
        )
    )

    fd = os.open(args.device, os.O_RDWR | os.O_CLOEXEC)
    try:
        for logical, block in blocks:
            delta = logical - args.system_logical
            if delta < 0 or delta + NODE_SIZE > args.system_length:
                raise RuntimeError("synthetic tree does not fit in system chunk")
            for physical_base in args.system_physical:
                physical = physical_base + delta
                if os.pwrite(fd, block, physical) != NODE_SIZE:
                    raise RuntimeError(f"short tree write at {physical}")

        if args.dev_stats_logical is not None:
            if args.metadata_logical is None or not args.metadata_physical:
                raise RuntimeError("dev stats requires synthetic metadata mapping")
            dev_stats_entry = dict(
                objectid=0,
                key_type=249,
                offset=1,
                raw_payload=b"\0" * 40,
            )
            dev_leaf = make_leaf(
                [dev_stats_entry], fsid, chunk_uuid,
                args.dev_stats_logical, args.dev_stats_generation, owner=4
            )
            delta = args.dev_stats_logical - args.metadata_logical
            for physical_base in args.metadata_physical:
                if os.pwrite(fd, dev_leaf, physical_base + delta) != NODE_SIZE:
                    raise RuntimeError("short dev stats leaf write")

        for spec in args.empty_tree or []:
            logical, generation, owner = (int(value, 0) for value in spec.split(","))
            empty = make_header(
                fsid, chunk_uuid, logical, generation, 0, 0, owner
            )
            checksum(empty)
            if (
                args.metadata_logical is not None
                and args.metadata_logical <= logical
                < args.metadata_logical + args.metadata_length
            ):
                bases = args.metadata_physical
                delta = logical - args.metadata_logical
            elif args.system_logical <= logical < args.system_logical + args.system_length:
                bases = args.system_physical
                delta = logical - args.system_logical
            else:
                raise RuntimeError(f"no synthetic physical mapping for {logical}")
            for physical_base in bases:
                if os.pwrite(fd, empty, physical_base + delta) != NODE_SIZE:
                    raise RuntimeError("short empty tree write")

        for spec in args.clone_leaf or []:
            source_logical, target_logical, generation, owner = (
                int(value, 0) for value in spec.split(",")
            )
            source_chunk = next(
                (
                    item for item in chunks
                    if item.get("stripes")
                    and item["offset"] <= source_logical
                    < item["offset"] + item["length"]
                ),
                None,
            )
            if not source_chunk:
                raise RuntimeError("no source mapping for cloned leaf")
            source_physical = (
                source_chunk["stripes"][0][1]
                + source_logical - source_chunk["offset"]
            )
            cloned = bytearray(os.pread(fd, NODE_SIZE, source_physical))
            if len(cloned) != NODE_SIZE or cloned[100] != 0:
                raise RuntimeError("clone source is not a readable leaf")
            struct.pack_into("<Q", cloned, 48, target_logical)
            struct.pack_into("<Q", cloned, 80, generation)
            struct.pack_into("<Q", cloned, 88, owner)
            checksum(cloned)
            if (
                args.metadata_logical is not None
                and args.metadata_logical <= target_logical
                < args.metadata_logical + args.metadata_length
            ):
                bases = args.metadata_physical
                delta = target_logical - args.metadata_logical
            else:
                raise RuntimeError("clone target has no synthetic mapping")
            for physical_base in bases:
                if os.pwrite(fd, cloned, physical_base + delta) != NODE_SIZE:
                    raise RuntimeError("short cloned leaf write")

        for super_offset in SUPER_OFFSETS:
            superblock = bytearray(os.pread(fd, SUPER_SIZE, super_offset))
            if len(superblock) != SUPER_SIZE:
                raise RuntimeError(f"cannot read super at {super_offset}")
            struct.pack_into("<Q", superblock, 88, args.chunk_root)
            struct.pack_into("<Q", superblock, 164, args.generation)
            struct.pack_into("<Q", superblock, 72, args.generation)
            struct.pack_into("<Q", superblock, 80, args.tree_root)
            superblock[198] = args.tree_root_level
            superblock[199] = 1
            checksum(superblock)
            if os.pwrite(fd, superblock, super_offset) != SUPER_SIZE:
                raise RuntimeError(f"short super write at {super_offset}")
        os.fsync(fd)
    finally:
        os.close(fd)

    print(
        f"wrote synthetic chunk tree: chunks={len(chunks)} leaves={len(groups)} "
        f"root={args.chunk_root} copies={len(args.system_physical)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
