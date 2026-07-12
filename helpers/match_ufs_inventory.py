#!/usr/bin/env python3
"""Match a UFS Explorer inventory export to a recovered Btrfs tree listing."""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


UNITS = {
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}


def normalized_path(value: str, fold_case: bool) -> str:
    value = unicodedata.normalize("NFC", value.strip()).replace("\\", "/")
    value = re.sub(r"^[A-Za-z]:", "", value)
    value = re.sub(r"/+", "/", value)
    if not value.startswith("/"):
        value = "/" + value
    return value.casefold() if fold_case else value


def parse_size(value: str, default_unit: str) -> int | None:
    text = value.strip().replace(",", "")
    if not text:
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)?", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or default_unit).lower()
    multiplier = UNITS.get(unit)
    return round(number * multiplier) if multiplier else None


def open_dict_rows(path: Path):
    sample = path.read_text(encoding="utf-8-sig", errors="replace")[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel_tab
    handle = path.open("r", encoding="utf-8-sig", errors="replace", newline="")
    return handle, csv.DictReader(handle, dialect=dialect)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ufs_inventory", type=Path)
    parser.add_argument("btrfs_listing", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ufs-path-column", default="path")
    parser.add_argument("--ufs-name-column")
    parser.add_argument("--ufs-size-column", default="size")
    parser.add_argument("--size-unit", default="B", choices=["B", "KB", "KiB", "MB", "MiB", "GB", "GiB"])
    parser.add_argument("--size-tolerance", type=int, default=1024)
    parser.add_argument("--case-insensitive", action="store_true")
    args = parser.parse_args()

    by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    with args.btrfs_listing.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("type") != "1":
                continue
            row["_path"] = normalized_path(row["path"], args.case_insensitive)
            by_path[row["_path"]].append(row)
            by_name[Path(row["_path"]).name].append(row)

    ufs_handle, ufs_rows = open_dict_rows(args.ufs_inventory)
    fieldnames = [
        "status", "ufs_size", "ufs_path", "btrfs_size", "rootid",
        "objectid", "btrfs_path",
    ]
    counts: dict[str, int] = defaultdict(int)
    with ufs_handle, args.output.open("w", encoding="utf-8", newline="") as out_handle:
        writer = csv.DictWriter(out_handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for ufs in ufs_rows:
            raw_path = ufs.get(args.ufs_path_column, "")
            if args.ufs_name_column and ufs.get(args.ufs_name_column):
                raw_path = raw_path.rstrip("/\\") + "/" + ufs[args.ufs_name_column]
            path = normalized_path(raw_path, args.case_insensitive)
            size = parse_size(ufs.get(args.ufs_size_column, ""), args.size_unit)

            candidates = by_path.get(path, [])
            status = "exact_path"
            if not candidates:
                candidates = by_name.get(Path(path).name, [])
                status = "unique_name"
            if size is not None:
                candidates = [
                    item for item in candidates
                    if abs(int(item["size"]) - size) <= args.size_tolerance
                ]
            if not candidates:
                status = "unmatched"
                candidates = [{}]
            elif len(candidates) > 1:
                status = "ambiguous"

            counts[status] += 1
            for match in candidates:
                writer.writerow({
                    "status": status,
                    "ufs_size": "" if size is None else size,
                    "ufs_path": raw_path,
                    "btrfs_size": match.get("size", ""),
                    "rootid": match.get("rootid", ""),
                    "objectid": match.get("objectid", ""),
                    "btrfs_path": match.get("path", ""),
                })

    print(" ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
