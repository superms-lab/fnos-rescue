#!/usr/bin/env python3
"""Fill missing Btrfs chunk stripes from a historical device-tree dump."""

from __future__ import annotations

import argparse
import collections
import re
import struct


DEV_KEY = re.compile(r"key \(1 DEV_EXTENT (\d+)\)")
DEV_DATA = re.compile(r"chunk_offset (\d+) length (\d+)")


def parse_device_tree(path: str):
    mappings = collections.defaultdict(list)
    physical = None
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = DEV_KEY.search(line)
            if match:
                physical = int(match.group(1))
                continue
            match = DEV_DATA.search(line)
            if match and physical is not None:
                logical, length = map(int, match.groups())
                pair = (physical, length)
                if pair not in mappings[logical]:
                    mappings[logical].append(pair)
                physical = None
    return mappings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_cache")
    parser.add_argument("device_tree_dump")
    parser.add_argument("output_cache")
    parser.add_argument("--infer-linear-diff", type=int)
    parser.add_argument(
        "--manual-stripes",
        action="append",
        default=[],
        help="logical=physical[,physical...] for verified overlay-only mappings",
    )
    parser.add_argument(
        "--allow-linear-overlap",
        action="store_true",
        help="emit inferred stripes overlapping later extents; disposable overlays only",
    )
    args = parser.parse_args()

    manual_stripes = {}
    for specification in args.manual_stripes:
        logical_text, physical_text = specification.split("=", 1)
        manual_stripes[int(logical_text, 0)] = [
            int(value, 0) for value in physical_text.split(",")
        ]

    devexts = parse_device_tree(args.device_tree_dump)
    with open(args.input_cache, "rb") as handle:
        header = handle.read(16)
        magic, version, count = struct.unpack("=8sII", header)
        if magic != b"BTRCHNK1" or version != 1:
            raise RuntimeError("unsupported cache")
        records = []
        dev_uuid = None
        for _ in range(count):
            raw = bytearray(handle.read(88))
            num_stripes = struct.unpack_from("=H", raw, 4)[0]
            stripes = [handle.read(32) for _stripe in range(num_stripes)]
            if stripes and dev_uuid is None:
                dev_uuid = stripes[0][16:32]
            records.append((raw, stripes))
    if dev_uuid is None:
        raise RuntimeError("cache has no device UUID")

    recovered = 0
    inferred = 0
    unmatched = []
    known_ranges = [
        (physical, physical + length)
        for values in devexts.values()
        for physical, length in values
    ]
    with open(args.output_cache, "wb") as out:
        out.write(header)
        for raw, stripes in records:
            kind = struct.unpack_from("=I", raw, 0)[0]
            logical = struct.unpack_from("=Q", raw, 32)[0]
            length = struct.unpack_from("=Q", raw, 48)[0]
            flags = struct.unpack_from("=Q", raw, 56)[0]
            if kind == 4 and not stripes:
                manual = manual_stripes.get(logical)
                if manual:
                    expected = 2 if flags & 32 else 1
                    if len(manual) != expected:
                        raise RuntimeError(
                            f"manual stripe count for {logical}: "
                            f"expected {expected}, got {len(manual)}"
                        )
                    struct.pack_into("=I", raw, 0, 1)
                    struct.pack_into("=H", raw, 4, expected)
                    struct.pack_into("=H", raw, 6, 1 if expected > 1 else 0)
                    stripes = [
                        struct.pack("=QQ16s", 1, physical, dev_uuid)
                        for physical in manual
                    ]
                    recovered += 1
                    out.write(raw)
                    for stripe in stripes:
                        out.write(stripe)
                    continue
                candidates = [
                    physical for physical, dev_length in devexts.get(logical, [])
                    if dev_length == length
                ]
                expected = 2 if flags & 32 else 1
                if len(candidates) == expected:
                    struct.pack_into("=I", raw, 0, 1)
                    struct.pack_into("=H", raw, 4, expected)
                    struct.pack_into("=H", raw, 6, 1 if expected > 1 else 0)
                    stripes = [
                        struct.pack("=QQ16s", 1, physical, dev_uuid)
                        for physical in sorted(candidates)
                    ]
                    recovered += 1
                elif args.infer_linear_diff is not None and flags == 1:
                    if length == 1 << 30:
                        candidate = logical + args.infer_linear_diff
                    elif length == 8 << 20 and logical < 22_020_096:
                        candidate = logical
                    else:
                        candidate = None
                    overlaps = candidate is not None and any(
                        candidate < end and candidate + length > start
                        for start, end in known_ranges
                    )
                    if candidate is not None and (
                        not overlaps or args.allow_linear_overlap
                    ):
                        struct.pack_into("=I", raw, 0, 1)
                        struct.pack_into("=H", raw, 4, 1)
                        struct.pack_into("=H", raw, 6, 0)
                        stripes = [struct.pack("=QQ16s", 1, candidate, dev_uuid)]
                        inferred += 1
                    else:
                        unmatched.append((logical, length, flags, candidates))
                else:
                    unmatched.append((logical, length, flags, candidates))
            out.write(raw)
            for stripe in stripes:
                out.write(stripe)

    print(
        f"device_extents={sum(len(value) for value in devexts.values())} "
        f"recovered_bad_chunks={recovered} inferred={inferred} "
        f"unmatched={len(unmatched)}"
    )
    for item in unmatched[:20]:
        print("UNMATCHED", *item)
    return 0 if recovered or inferred else 3


if __name__ == "__main__":
    raise SystemExit(main())
