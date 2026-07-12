from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .devices import require_block_device
from .errors import JobControlRequested, RescueError
from .jobs import JobStore, RecoveryJob
from .plugins.fnos_btrfs import FnosBtrfsPlugin
from .runner import run, run_interruptible
from .safety import assert_read_only
from .verify import sha256_file


FSID = re.compile(r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$")


def _job_directory(store: JobStore, job: RecoveryJob) -> Path:
    return store.root / job.job_id


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def execute_btrfs_probe(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    device = Path(str(job.parameters.get("device", "")))
    store.transition(job, "running", current_step="probe-superblocks")
    evidence = FnosBtrfsPlugin().probe(device)
    target = _job_directory(store, job) / "superblocks.json"
    _write_json(target, evidence)
    store.complete_step(job, "probe-superblocks", {"artifact": str(target), "mirrors": 3})
    store.transition(job, "completed")
    return job


def _scan_argv(parameters: dict[str, Any], device: Path) -> list[str]:
    scanner = Path(str(parameters.get("scanner", ""))).expanduser().resolve()
    if not scanner.is_file() or not scanner.stat().st_mode & 0o111:
        raise RescueError(f"root scanner is not executable: {scanner}")
    fsid = str(parameters.get("fsid", "")).strip()
    if not FSID.fullmatch(fsid):
        raise RescueError("root scan requires a valid Btrfs FSID")
    argv = [str(scanner), str(device), fsid]
    start = parameters.get("start_gib")
    end = parameters.get("end_gib")
    if start is not None:
        start_value = int(start)
        if start_value < 0:
            raise RescueError("start_gib cannot be negative")
        argv.append(str(start_value))
    if end is not None:
        if start is None:
            raise RescueError("end_gib requires start_gib")
        end_value = int(end)
        if end_value <= int(start):
            raise RescueError("end_gib must be greater than start_gib")
        argv.append(str(end_value))
    return argv


def execute_btrfs_root_scan(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    device = require_block_device(str(job.parameters.get("device", "")))
    assert_read_only(device)
    argv = _scan_argv(job.parameters, device)
    store.transition(job, "running", current_step="scan-historical-roots")
    result = run(argv, timeout=float(job.parameters.get("timeout", 86400)))
    directory = _job_directory(store, job)
    log = directory / "root-scan.log"
    log.write_text(result.stdout)
    log.chmod(0o600)
    if result.stderr:
        errors = directory / "root-scan.stderr.log"
        errors.write_text(result.stderr)
        errors.chmod(0o600)
    summary = {
        "argv": list(result.argv),
        "returncode": result.returncode,
        "stdout_bytes": len(result.stdout.encode()),
        "stderr_bytes": len(result.stderr.encode()),
        "artifact": str(log),
    }
    _write_json(directory / "root-scan.json", summary)
    store.complete_step(job, "scan-historical-roots", summary)
    store.transition(job, "completed")
    return job


def _private_btrfs(parameters: dict[str, Any]) -> Path:
    tool = Path(str(parameters.get("private_btrfs", ""))).expanduser().resolve()
    if not tool.is_file() or not tool.stat().st_mode & 0o111:
        raise RescueError(f"private btrfs tool is not executable: {tool}")
    return tool


def _readonly_device(parameters: dict[str, Any]) -> Path:
    device = require_block_device(str(parameters.get("device", "")))
    assert_read_only(device)
    return device


def _positive_integer(parameters: dict[str, Any], name: str) -> int:
    value = int(parameters.get(name, 0))
    if value <= 0:
        raise RescueError(f"{name} must be a positive integer")
    return value


def execute_btrfs_chunk_cache(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    device = _readonly_device(job.parameters)
    tool = _private_btrfs(job.parameters)
    cache = _job_directory(store, job) / "chunk-mappings.cache"
    store.transition(job, "running", current_step="build-chunk-cache")
    result = run(
        [tool, "rescue", "chunk-recover", "-y", device],
        timeout=float(job.parameters.get("timeout", 86400)),
        env={"BTRFS_CHUNK_CACHE_SAVE": str(cache), "BTRFS_CHUNK_CACHE_ONLY": "1"},
    )
    if not cache.is_file() or cache.stat().st_size == 0:
        raise RescueError("private btrfs tool did not create a non-empty chunk cache")
    cache.chmod(0o600)
    log = _job_directory(store, job) / "chunk-cache.log"
    log.write_text(result.stdout + result.stderr)
    log.chmod(0o600)
    details = {"artifact": str(cache), "bytes": cache.stat().st_size, "log": str(log)}
    store.complete_step(job, "build-chunk-cache", details)
    store.transition(job, "completed")
    return job


def _required_file(parameters: dict[str, Any], name: str) -> Path:
    path = Path(str(parameters.get(name, ""))).expanduser().resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise RescueError(f"{name} is missing or empty: {path}")
    return path


def execute_btrfs_list(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    device = _readonly_device(job.parameters)
    tool = _private_btrfs(job.parameters)
    cache = _required_file(job.parameters, "chunk_cache")
    fs_root = _positive_integer(job.parameters, "filesystem_root")
    inventory = _job_directory(store, job) / "btrfs-files.tsv"
    store.transition(job, "running", current_step="list-filesystem-tree")
    result = run(
        [tool, "rescue", "chunk-recover", "-y", device],
        timeout=float(job.parameters.get("timeout", 3600)),
        env={
            "BTRFS_CHUNK_CACHE_LOAD": str(cache),
            "BTRFS_FORCE_FS_ROOT": str(fs_root),
            "BTRFS_LIST_PATHS": str(inventory),
        },
    )
    if not inventory.is_file() or inventory.stat().st_size == 0:
        raise RescueError("private btrfs tool did not create a file inventory")
    inventory.chmod(0o600)
    log = _job_directory(store, job) / "list.log"
    log.write_text(result.stdout + result.stderr)
    log.chmod(0o600)
    details = {"artifact": str(inventory), "bytes": inventory.stat().st_size, "log": str(log)}
    store.complete_step(job, "list-filesystem-tree", details)
    store.transition(job, "completed")
    return job


def execute_btrfs_extract_inode(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    device = _readonly_device(job.parameters)
    tool = _private_btrfs(job.parameters)
    cache = _required_file(job.parameters, "chunk_cache")
    fs_root = _positive_integer(job.parameters, "filesystem_root")
    rootid = _positive_integer(job.parameters, "rootid")
    inode = _positive_integer(job.parameters, "inode")
    output = _job_directory(store, job) / "extracted.bin"
    output.unlink(missing_ok=True)
    environment = {
        "BTRFS_CHUNK_CACHE_LOAD": str(cache),
        "BTRFS_FORCE_FS_ROOT": str(fs_root),
        "BTRFS_EXTRACT_ROOTID": str(rootid),
        "BTRFS_EXTRACT_INODE": str(inode),
        "BTRFS_EXTRACT_PATH": str(output),
    }
    historical_root = job.parameters.get("historical_root")
    if historical_root is not None:
        environment["BTRFS_FORCE_EXTRACT_ROOT"] = str(int(historical_root))
    store.transition(job, "running", current_step="extract-inode")
    result = run(
        [tool, "rescue", "chunk-recover", "-y", device],
        timeout=float(job.parameters.get("timeout", 3600)),
        env=environment,
    )
    if not output.is_file():
        raise RescueError("private btrfs tool did not create an extracted file")
    expected_size = job.parameters.get("expected_size")
    if expected_size is not None and output.stat().st_size != int(expected_size):
        output.unlink(missing_ok=True)
        raise RescueError("extracted file size does not match expected_size")
    output.chmod(0o600)
    log = _job_directory(store, job) / "extract.log"
    log.write_text(result.stdout + result.stderr)
    log.chmod(0o600)
    details = {"artifact": str(output), "bytes": output.stat().st_size, "log": str(log)}
    store.complete_step(job, "extract-inode", details)
    store.transition(job, "completed")
    return job


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise RescueError(f"extraction path must be relative and contained: {value}")
    return path


def execute_btrfs_extract_batch(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    device = _readonly_device(job.parameters)
    tool = _private_btrfs(job.parameters)
    cache = _required_file(job.parameters, "chunk_cache")
    fs_root = _positive_integer(job.parameters, "filesystem_root")
    items = job.parameters.get("items")
    if not isinstance(items, list) or not items:
        raise RescueError("batch extraction requires a non-empty items list")
    output_root = _job_directory(store, job) / "extracted"
    output_root.mkdir(mode=0o700, exist_ok=True)
    failures = 0
    results: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise RescueError("each extraction item must be an object")
        relative = _safe_relative(str(item.get("path", "")))
        step = relative.as_posix()
        if step in job.completed_steps:
            continue
        action = store.requested_action(job)
        if action in {"pause", "cancel"}:
            store.transition(job, "paused" if action == "pause" else "cancelled")
            return job
        rootid = int(item.get("rootid", 0))
        inode = int(item.get("inode", 0))
        expected_size = int(item.get("expected_size", -1))
        if rootid <= 0 or inode <= 0 or expected_size < 0:
            raise RescueError(f"invalid extraction metadata for {step}")
        target = output_root / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.unlink(missing_ok=True)
        environment = {
            "BTRFS_CHUNK_CACHE_LOAD": str(cache),
            "BTRFS_FORCE_FS_ROOT": str(fs_root),
            "BTRFS_EXTRACT_ROOTID": str(rootid),
            "BTRFS_EXTRACT_INODE": str(inode),
            "BTRFS_EXTRACT_PATH": str(target),
        }
        if item.get("historical_root") is not None:
            environment["BTRFS_FORCE_EXTRACT_ROOT"] = str(int(item["historical_root"]))
        store.transition(job, "running", current_step=step)
        try:
            run_interruptible(
                [tool, "rescue", "chunk-recover", "-y", device],
                timeout=float(job.parameters.get("per_file_timeout", 3600)),
                env=environment,
                control=lambda: store.requested_action(job),
            )
            if not target.is_file() or target.stat().st_size != expected_size:
                raise RescueError("extracted file size does not match expected_size")
            digest = sha256_file(target)
            target.chmod(0o600)
            result = {"path": step, "bytes": expected_size, "sha256": digest, "artifact": str(target)}
            results.append(result)
            store.complete_step(job, step, result)
        except JobControlRequested as exc:
            target.unlink(missing_ok=True)
            store.transition(job, "paused" if exc.action == "pause" else "cancelled", current_step=step)
            return job
        except (OSError, RescueError) as exc:
            target.unlink(missing_ok=True)
            store.record_failure(job, step, str(exc))
            failures += 1
    _write_json(_job_directory(store, job) / "batch-results.json", results)
    store.transition(job, "completed_with_errors" if failures else "completed")
    return job
