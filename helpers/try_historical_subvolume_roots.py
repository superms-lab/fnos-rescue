#!/usr/bin/env python3
"""Try exact inodes against scanned historical subvolume roots."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def safe_destination(root: str, relative_path: str) -> str:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"destination path must stay inside root: {relative_path}")
    root_input = Path(root).absolute()
    if root_input.is_symlink():
        raise ValueError(f"destination root symlink is not allowed: {root_input}")
    root_path = root_input.resolve()
    current = root_path
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError(f"destination symlink is not allowed: {current}")
    return str(current)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="TSV containing byte size, inode and relative path")
    parser.add_argument("device")
    parser.add_argument("chunk_cache")
    parser.add_argument("filesystem_root", help="coherent top-level filesystem root bytenr")
    parser.add_argument("subvolume_roots", help="comma-separated historical root bytenrs")
    parser.add_argument("private_btrfs")
    parser.add_argument("destination_root")
    parser.add_argument("output_log")
    parser.add_argument("--rootid", default="257")
    parser.add_argument("--size-column", default="大小(bytes)")
    parser.add_argument("--inode-column", default="inode")
    parser.add_argument("--path-column", default="相对路径")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()

    roots = [int(value, 0) for value in args.subvolume_roots.split(",") if value]
    rows = []
    with open(args.manifest, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            try:
                rows.append(
                    (
                        int(row[args.size_column]),
                        int(row[args.inode_column]),
                        row[args.path_column],
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

    started = time.monotonic()
    attempts = 0
    copied_bytes = 0
    successes = []
    failures = []
    scratch = tempfile.mkdtemp(prefix="btrfs-historical-roots-")
    try:
        for expected_size, inode, relative_path in rows:
            recovered = None
            errors = []
            for root in roots:
                attempts += 1
                extracted = os.path.join(scratch, f"{inode}-{root}.recovered")
                environment = os.environ.copy()
                environment.update(
                    {
                        "BTRFS_CHUNK_CACHE_LOAD": args.chunk_cache,
                        "BTRFS_FORCE_FS_ROOT": args.filesystem_root,
                        "BTRFS_EXTRACT_ROOTID": args.rootid,
                        "BTRFS_FORCE_EXTRACT_ROOT": str(root),
                        "BTRFS_EXTRACT_INODE": str(inode),
                        "BTRFS_EXTRACT_PATH": extracted,
                    }
                )
                try:
                    result = subprocess.run(
                        [
                            args.private_btrfs,
                            "rescue",
                            "chunk-recover",
                            "-y",
                            args.device,
                        ],
                        env=environment,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=args.timeout,
                        check=False,
                    )
                    actual_size = os.path.getsize(extracted)
                    if actual_size == expected_size and expected_size > 0:
                        recovered = (root, extracted)
                        break
                    errors.append(f"{root}:size={actual_size}:rc={result.returncode}")
                except Exception as error:
                    errors.append(f"{root}:{error}")
                finally:
                    if recovered is None:
                        try:
                            os.unlink(extracted)
                        except OSError:
                            pass

                if attempts % args.progress_every == 0:
                    elapsed = time.monotonic() - started
                    print(
                        f"attempts={attempts} files_ok={len(successes)} "
                        f"rate={attempts / elapsed:.1f}attempts/s",
                        flush=True,
                    )

            if recovered is None:
                failures.append((expected_size, inode, relative_path, ";".join(errors)))
                continue

            root, extracted = recovered
            try:
                destination = safe_destination(args.destination_root, relative_path)
            except ValueError as error:
                failures.append((expected_size, inode, relative_path, str(error)))
                os.unlink(extracted)
                continue
            temporary = destination + ".historical-root-tmp"
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            digest = hashlib.sha256()
            with open(extracted, "rb") as source, open(temporary, "wb") as target:
                while True:
                    block = source.read(4 * 1024 * 1024)
                    if not block:
                        break
                    target.write(block)
                    digest.update(block)
            if os.path.getsize(temporary) != expected_size:
                os.unlink(temporary)
                failures.append((expected_size, inode, relative_path, "destination short write"))
                continue
            os.replace(temporary, destination)
            copied_bytes += expected_size
            successes.append(
                (expected_size, inode, root, digest.hexdigest(), relative_path)
            )
            os.unlink(extracted)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    with open(args.output_log, "w", encoding="utf-8", newline="") as handle:
        handle.write("状态\t大小(bytes)\tinode\t历史根\tSHA256\t相对路径\t错误\n")
        for size, inode, root, digest, path in successes:
            handle.write(f"成功\t{size}\t{inode}\t{root}\t{digest}\t{path}\t\n")
        for size, inode, path, error in failures:
            clean_error = error.replace("\t", " ").replace("\n", " ")
            handle.write(f"失败\t{size}\t{inode}\t\t\t{path}\t{clean_error}\n")

    elapsed = time.monotonic() - started
    print(
        f"done files={len(rows)} ok={len(successes)} failed={len(failures)} "
        f"attempts={attempts} elapsed={elapsed:.3f}s "
        f"attempt_rate={attempts / elapsed if elapsed else 0:.1f}/s "
        f"copied={copied_bytes} copy_rate={copied_bytes / elapsed / 2**20 if elapsed else 0:.2f}MiB/s"
    )
    return 0 if successes else 2


if __name__ == "__main__":
    raise SystemExit(main())
