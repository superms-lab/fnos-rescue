#!/usr/bin/env python3
"""Try exact inodes against scanned historical subvolume roots."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from fnos_rescue.destinations import assert_destination_ready, inspect_destination
from fnos_rescue.safety import assert_destination_not_source, assert_source_graph_read_only
from fnos_rescue.verify import sha256_file, verify_file


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


def normalized_fsid(value: object) -> str:
    fsid = str(value or "").lower().replace("-", "")
    if len(fsid) != 32 or any(char not in "0123456789abcdef" for char in fsid):
        raise ValueError("invalid FSID in evidence")
    return fsid


def root_evidence(candidates: list[dict], logical: int, owner: int, fsid: str) -> dict:
    matches = [
        item for item in candidates
        if int(item.get("logical", -1)) == logical
        and int(item.get("owner", -1)) == owner
        and normalized_fsid(item.get("fsid")) == fsid
    ]
    identities = {(int(item["generation"]), int(item["level"])) for item in matches}
    if not matches or len(identities) != 1:
        raise ValueError(f"missing or ambiguous evidence for root {logical} owner {owner}")
    return matches[0]


def forced_root_environment(prefix: str, evidence: dict) -> dict[str, str]:
    return {
        prefix: str(evidence["logical"]),
        f"{prefix}_FSID": normalized_fsid(evidence["fsid"]),
        f"{prefix}_OWNER": str(evidence["owner"]),
        f"{prefix}_GENERATION": str(evidence["generation"]),
        f"{prefix}_LEVEL": str(evidence["level"]),
    }


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
    parser.add_argument("--root-evidence", required=True, help="root-candidates.json from the same case")
    parser.add_argument("--cache-manifest", required=True, help="chunk cache provenance manifest")
    parser.add_argument("--rootid", default="257")
    parser.add_argument("--size-column", default="大小(bytes)")
    parser.add_argument("--inode-column", default="inode")
    parser.add_argument("--path-column", default="相对路径")
    parser.add_argument("--sha256-column", default="SHA256")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()

    assert_source_graph_read_only(args.device)
    destination_facts = inspect_destination(args.destination_root)
    assert_destination_not_source(args.device, destination_facts.existing_ancestor)
    assert_destination_ready(destination_facts)

    cache_manifest = json.loads(Path(args.cache_manifest).read_text())
    fsid = normalized_fsid(cache_manifest.get("fsid"))
    cache = Path(args.chunk_cache).resolve()
    if cache_manifest.get("cache", {}).get("sha256") != sha256_file(cache):
        raise ValueError("chunk cache hash does not match its provenance manifest")
    if cache_manifest.get("cache", {}).get("bytes") != cache.stat().st_size:
        raise ValueError("chunk cache size does not match its provenance manifest")
    if cache_manifest.get("recovery_layer") != str(Path(args.device).resolve()):
        raise ValueError("chunk cache belongs to a different recovery layer")
    if cache_manifest.get("tool", {}).get("sha256") != sha256_file(Path(args.private_btrfs)):
        raise ValueError("private btrfs binary differs from the cache-producing tool")
    evidence_path = Path(args.root_evidence).resolve()
    evidence_summary = json.loads((evidence_path.parent / "root-scan.json").read_text())
    if evidence_summary.get("candidate_sha256") != sha256_file(evidence_path):
        raise ValueError("root evidence hash does not match its scan summary")
    evidence_payload = json.loads(evidence_path.read_text())
    if normalized_fsid(evidence_payload.get("fsid")) != fsid:
        raise ValueError("root evidence FSID differs from the chunk cache FSID")
    candidates = evidence_payload.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("root evidence candidate list is invalid")

    roots = [int(value, 0) for value in args.subvolume_roots.split(",") if value]
    filesystem_evidence = root_evidence(candidates, int(args.filesystem_root, 0), 5, fsid)
    rootid_value = int(args.rootid, 0)
    subvolume_evidence = {
        root: root_evidence(candidates, root, rootid_value, fsid) for root in roots
    }
    rows = []
    with open(args.manifest, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            try:
                rows.append(
                    (
                        int(row[args.size_column]),
                        int(row[args.inode_column]),
                        row[args.path_column],
                        row.get(args.sha256_column, "").strip() or None,
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
        for expected_size, inode, relative_path, expected_sha256 in rows:
            recovered = None
            errors = []
            for root in roots:
                attempts += 1
                extracted = os.path.join(scratch, f"{inode}-{root}.recovered")
                environment = os.environ.copy()
                environment.update(
                    {
                        "BTRFS_CHUNK_CACHE_LOAD": args.chunk_cache,
                        "BTRFS_EXTRACT_ROOTID": args.rootid,
                        "BTRFS_EXTRACT_INODE": str(inode),
                        "BTRFS_EXTRACT_PATH": extracted,
                    }
                )
                environment.update(forced_root_environment("BTRFS_FORCE_FS_ROOT", filesystem_evidence))
                environment.update(forced_root_environment("BTRFS_FORCE_EXTRACT_ROOT", subvolume_evidence[root]))
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
                    verification = verify_file(
                        extracted,
                        expected_size=expected_size,
                        expected_sha256=expected_sha256,
                        expected_empty=expected_size == 0,
                    )
                    if result.returncode == 0 and verification.validation_ok is True:
                        recovered = (root, extracted)
                        break
                    errors.append(
                        f"{root}:size={actual_size}:rc={result.returncode}:"
                        f"validation={verification.classification}:"
                        f"{verification.validation_error or ''}"
                    )
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
                target.flush()
                os.fsync(target.fileno())
            if os.path.getsize(temporary) != expected_size:
                os.unlink(temporary)
                failures.append((expected_size, inode, relative_path, "destination short write"))
                continue
            source_digest = digest.hexdigest()
            if sha256_file(Path(temporary)) != source_digest:
                os.unlink(temporary)
                failures.append((expected_size, inode, relative_path, "temporary destination reread hash mismatch"))
                continue
            os.replace(temporary, destination)
            directory_fd = os.open(os.path.dirname(destination), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            destination_digest = sha256_file(Path(destination))
            if destination_digest != source_digest:
                failures.append((expected_size, inode, relative_path, "final destination reread hash mismatch"))
                continue
            copied_bytes += expected_size
            successes.append(
                (expected_size, inode, root, destination_digest, relative_path)
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
    return 0 if rows and len(successes) == len(rows) and not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
