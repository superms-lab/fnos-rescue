#!/usr/bin/env python3
"""Copy exact recovery paths only after a complete source read and hash check."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="TSV with expected byte size and relative path")
    parser.add_argument("source_root")
    parser.add_argument("destination_root")
    parser.add_argument("output_log")
    parser.add_argument("--size-column", default="原始大小(bytes)")
    parser.add_argument("--path-column", default="相对路径")
    parser.add_argument("--buffer-mib", type=int, default=4)
    parser.add_argument("--progress-every", type=int, default=10)
    args = parser.parse_args()

    candidates = []
    with open(args.manifest, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            try:
                size = int(row[args.size_column])
            except (KeyError, TypeError, ValueError):
                continue
            if size > 0:
                candidates.append((size, row[args.path_column]))

    started = time.monotonic()
    copied_bytes = 0
    successes = []
    failures = []
    buffer_size = args.buffer_mib * 1024 * 1024

    for index, (expected_size, relative_path) in enumerate(candidates, 1):
        source = os.path.join(args.source_root, relative_path)
        destination = os.path.join(args.destination_root, relative_path)
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
            if copied != expected_size:
                raise OSError(f"short read {copied}/{expected_size}")
            os.replace(temporary, destination)
            copied_bytes += copied
            successes.append(
                (expected_size, digest.hexdigest(), magic.hex(), relative_path)
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
    return 0 if successes else 2


if __name__ == "__main__":
    raise SystemExit(main())
