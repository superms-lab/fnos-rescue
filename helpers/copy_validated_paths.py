#!/usr/bin/env python3
"""Copy exact recovery paths only after a complete source read and hash check."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import time
from pathlib import Path

from fnos_rescue.destinations import assert_destination_ready, inspect_destination
from fnos_rescue.safety import assert_destination_not_source, assert_source_graph_read_only
from fnos_rescue.verify import sha256_file, verify_file


def safe_path(root: str, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"path must stay inside root: {relative_path}")
    root_input = Path(root).absolute()
    if root_input.is_symlink():
        raise ValueError(f"root symlink is not allowed: {root_input}")
    root_path = root_input.resolve()
    current = root_path
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlink is not allowed in recovery path: {current}")
    resolved = current.resolve()
    if resolved != root_path and root_path not in resolved.parents:
        raise ValueError(f"path escapes root: {relative_path}")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="TSV with expected byte size and relative path")
    parser.add_argument("source_root")
    parser.add_argument("destination_root")
    parser.add_argument("output_log")
    parser.add_argument("--source-device", required=True, help="original physical source device")
    parser.add_argument("--size-column", default="原始大小(bytes)")
    parser.add_argument("--path-column", default="相对路径")
    parser.add_argument("--sha256-column", default="SHA256")
    parser.add_argument("--buffer-mib", type=int, default=4)
    parser.add_argument("--progress-every", type=int, default=10)
    args = parser.parse_args()

    assert_source_graph_read_only(args.source_device)
    destination_facts = inspect_destination(args.destination_root)
    assert_destination_not_source(args.source_device, destination_facts.existing_ancestor)
    assert_destination_ready(destination_facts)

    candidates = []
    with open(args.manifest, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            try:
                size = int(row[args.size_column])
            except (KeyError, TypeError, ValueError):
                continue
            if size >= 0:
                candidates.append((size, row[args.path_column], row.get(args.sha256_column, "").strip() or None))

    started = time.monotonic()
    copied_bytes = 0
    successes = []
    failures = []
    buffer_size = args.buffer_mib * 1024 * 1024

    for index, (expected_size, relative_path, expected_sha256) in enumerate(candidates, 1):
        try:
            source = str(safe_path(args.source_root, relative_path))
            destination = str(safe_path(args.destination_root, relative_path))
        except ValueError as error:
            failures.append((expected_size, relative_path, str(error)))
            continue
        temporary = destination + ".codex-recover-tmp"
        digest = hashlib.sha256()
        copied = 0
        magic = b""
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            if os.path.exists(temporary):
                os.unlink(temporary)
            with open(source, "rb", buffering=0) as src, open(
                temporary, "wb", buffering=0
            ) as dst:
                while True:
                    block = src.read(buffer_size)
                    if not block:
                        break
                    if not magic:
                        magic = block[:8]
                    dst.write(block)
                    digest.update(block)
                    copied += len(block)
                dst.flush()
                os.fsync(dst.fileno())
            if copied != expected_size:
                raise OSError(f"short read {copied}/{expected_size}")
            source_digest = digest.hexdigest()
            temporary_digest = sha256_file(Path(temporary))
            if temporary_digest != source_digest:
                raise OSError("temporary destination reread hash mismatch")
            os.replace(temporary, destination)
            directory_fd = os.open(os.path.dirname(destination), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            destination_digest = sha256_file(Path(destination))
            if destination_digest != source_digest:
                raise OSError("final destination reread hash mismatch")
            verification = verify_file(
                destination,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                expected_empty=expected_size == 0,
            )
            if verification.validation_ok is not True:
                raise OSError(verification.validation_error or "destination content is unvalidated")
            copied_bytes += copied
            successes.append(
                (expected_size, destination_digest, magic.hex(), relative_path)
            )
        except Exception as error:  # Recovery must continue after per-file errors.
            try:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            except OSError:
                pass
            failures.append((expected_size, relative_path, str(error)))

        if index % args.progress_every == 0 or index == len(candidates):
            elapsed = time.monotonic() - started
            speed = copied_bytes / elapsed / 2**20 if elapsed else 0
            print(
                f"progress={index}/{len(candidates)} ok={len(successes)} "
                f"failed={len(failures)} copied={copied_bytes} "
                f"speed={speed:.2f}MiB/s",
                flush=True,
            )

    with open(args.output_log, "w", encoding="utf-8", newline="") as handle:
        handle.write("状态\t大小(bytes)\tSHA256\t文件头\t相对路径\t错误\n")
        for size, digest, magic, path in successes:
            handle.write(f"成功\t{size}\t{digest}\t{magic}\t{path}\t\n")
        for size, path, error in failures:
            clean_error = error.replace("\t", " ").replace("\n", " ")
            handle.write(f"失败\t{size}\t\t\t{path}\t{clean_error}\n")

    elapsed = time.monotonic() - started
    speed = copied_bytes / elapsed / 2**20 if elapsed else 0
    print(
        f"done ok={len(successes)} failed={len(failures)} "
        f"copied={copied_bytes} elapsed={elapsed:.3f}s speed={speed:.2f}MiB/s"
    )
    return 0 if candidates and len(successes) == len(candidates) and not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
