from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import fcntl
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .errors import RescueError
from .destinations import assert_destination_ready, inspect_destination
from .jobs import JobStore, RecoveryJob
from .safety import assert_destination_not_source
from .verify import iter_files, sha256_file, verify_file
from .overlays import (
    execute_overlay_cleanup,
    execute_overlay_connect,
    execute_overlay_create,
    execute_overlay_disconnect,
)
from .btrfs_jobs import (
    execute_btrfs_chunk_cache,
    execute_btrfs_extract_inode,
    execute_btrfs_extract_batch,
    execute_btrfs_list,
    execute_btrfs_probe,
    execute_btrfs_root_scan,
)


def _write_results(store: JobStore, job: RecoveryJob, results: list[dict[str, Any]]) -> Path:
    target = store.root / job.job_id / "results.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(target)
    return target


def execute_verify(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    source = Path(str(job.parameters.get("path", ""))).expanduser().resolve()
    limit = int(job.parameters.get("limit", 10))
    if not source.exists():
        raise RescueError(f"verification path does not exist: {source}")
    if limit < 1:
        raise RescueError("verification limit must be at least 1")

    result_path = store.root / job.job_id / "results.json"
    results = json.loads(result_path.read_text()) if result_path.is_file() else []
    completed = set(job.completed_steps)
    failures = 0
    for candidate in iter_files(source):
        if _apply_control(store, job):
            return job
        if len(results) >= limit:
            break
        step = str(candidate.resolve())
        if step in completed or candidate.stat().st_size == 0:
            continue
        store.transition(job, "running", current_step=step)
        try:
            result = asdict(verify_file(candidate))
            results.append(result)
            _write_results(store, job, results)
            store.complete_step(job, step, {"sha256": result["sha256"]})
        except (OSError, ValueError) as exc:
            store.record_failure(job, step, str(exc))
            failures += 1
            continue
        completed.add(step)
    store.transition(job, "completed_with_errors" if failures else "completed")
    return job


def _apply_control(store: JobStore, job: RecoveryJob) -> bool:
    action = store.requested_action(job)
    if action == "pause":
        store.transition(job, "paused", current_step=job.current_step)
        return True
    if action == "cancel":
        store.transition(job, "cancelled", current_step=job.current_step)
        return True
    return False


def _assert_no_symlink_components(root: Path, path: Path) -> None:
    relative = path.relative_to(root)
    current = root
    if current.is_symlink():
        raise RescueError(f"symlink is not allowed in recovery path: {current}")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RescueError(f"symlink is not allowed in recovery path: {current}")


def _assert_no_existing_symlink_chain(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise RescueError(f"symlink is not allowed in path: {current}")


def _directory_files(source_root: Path, directory: Path) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    for current, directories, names in os.walk(directory, followlinks=False):
        current_path = Path(current)
        for name in list(directories):
            child = current_path / name
            if child.is_symlink():
                raise RescueError(f"symlink directory is not allowed: {child}")
        for name in names:
            child = current_path / name
            if child.is_symlink():
                raise RescueError(f"symlink file is not allowed: {child}")
            if child.is_file():
                files.append((child, child.relative_to(source_root)))
    return files


def _selected_files(source_root: Path, selections: list[str]) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    for selection in selections:
        relative = Path(selection)
        if relative.is_absolute() or ".." in relative.parts:
            raise RescueError(f"selected path must stay inside source root: {selection}")
        lexical_source = source_root / relative
        _assert_no_symlink_components(source_root, lexical_source)
        source = lexical_source.resolve()
        if source != source_root and source_root not in source.parents:
            raise RescueError(f"selected path escapes source root: {selection}")
        if not source.exists():
            raise RescueError(f"selected path does not exist: {selection}")
        if source.is_file():
            files.append((source, relative))
        else:
            files.extend(_directory_files(source_root, source))
    return files


def _assert_safe_target(destination: Path, target: Path) -> None:
    if target != destination and destination not in target.parents:
        raise RescueError(f"copy target escapes destination: {target}")
    current = destination
    if current.exists() and current.is_symlink():
        raise RescueError(f"destination symlink is not allowed: {current}")
    for part in target.relative_to(destination).parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise RescueError(f"target symlink is not allowed: {current}")


def execute_copy(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    source_input = Path(str(job.parameters.get("source_root", ""))).expanduser().absolute()
    destination_input = Path(str(job.parameters.get("destination", ""))).expanduser().absolute()
    _assert_no_existing_symlink_chain(source_input)
    _assert_no_existing_symlink_chain(destination_input)
    source_root = source_input.resolve()
    destination = destination_input.resolve()
    source_device = str(job.parameters.get("source_device", "")).strip()
    selections = job.parameters.get("paths")
    if not source_root.is_dir():
        raise RescueError(f"copy source root is not a directory: {source_root}")
    if not isinstance(selections, list) or not selections:
        raise RescueError("copy job requires a non-empty paths list")
    if not source_device:
        raise RescueError("copy job requires source_device for physical-disk safety checking")
    if destination == source_root or destination in source_root.parents or source_root in destination.parents:
        raise RescueError("copy destination must be outside the source tree")
    selected = _selected_files(source_root, [str(item) for item in selections])
    required_bytes = sum(source.stat().st_size for source, _ in selected)
    destination_facts = inspect_destination(destination)
    assert_destination_not_source(source_device, destination_facts.existing_ancestor)
    assert_destination_ready(destination_facts, required_bytes)
    destination.mkdir(parents=True, exist_ok=True)

    failures = 0
    for source, relative in selected:
        if _apply_control(store, job):
            return job
        step = relative.as_posix()
        if step in job.completed_steps:
            continue
        target = destination / relative
        _assert_safe_target(destination, target)
        temporary = target.with_name(f".{target.name}.{job.job_id}.tmp")
        _assert_safe_target(destination, temporary)
        store.transition(job, "running", current_step=step)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            before = source.stat()
            temporary.unlink(missing_ok=True)
            shutil.copy2(source, temporary)
            after = source.stat()
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise RescueError("source changed while copying")
            source_hash = sha256_file(source)
            target_hash = sha256_file(temporary)
            if source_hash != target_hash:
                raise RescueError("checksum mismatch after copy")
            temporary.replace(target)
            store.complete_step(job, step, {"sha256": target_hash, "destination": str(target)})
        except (OSError, RescueError) as exc:
            temporary.unlink(missing_ok=True)
            store.record_failure(job, step, str(exc))
            failures += 1
    store.transition(job, "completed_with_errors" if failures else "completed")
    return job


@contextmanager
def _job_lock(store: JobStore, job_id: str):
    target = store.root / job_id / "worker.lock"
    with target.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RescueError(f"job already has an active worker: {job_id}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def execute_job(store: JobStore, job_id: str) -> RecoveryJob:
    with _job_lock(store, job_id):
        return _execute_locked(store, job_id)


def _execute_locked(store: JobStore, job_id: str) -> RecoveryJob:
    job = store.load(job_id)
    if job.status in {"completed", "cancelled"}:
        return job
    try:
        if job.kind == "verify":
            return execute_verify(store, job)
        if job.kind == "copy":
            return execute_copy(store, job)
        if job.kind == "btrfs-probe":
            return execute_btrfs_probe(store, job)
        if job.kind == "btrfs-root-scan":
            return execute_btrfs_root_scan(store, job)
        if job.kind == "btrfs-chunk-cache":
            return execute_btrfs_chunk_cache(store, job)
        if job.kind == "btrfs-list":
            return execute_btrfs_list(store, job)
        if job.kind == "btrfs-extract-inode":
            return execute_btrfs_extract_inode(store, job)
        if job.kind == "btrfs-extract-batch":
            return execute_btrfs_extract_batch(store, job)
        if job.kind == "overlay-create":
            return execute_overlay_create(store, job)
        if job.kind == "overlay-connect":
            return execute_overlay_connect(store, job)
        if job.kind == "overlay-disconnect":
            return execute_overlay_disconnect(store, job)
        if job.kind == "overlay-cleanup":
            return execute_overlay_cleanup(store, job)
        raise RescueError(f"unsupported job kind: {job.kind}")
    except Exception as exc:
        store.transition(job, "failed", current_step=job.current_step, error=str(exc))
        raise


def start_background(store: JobStore, job: RecoveryJob) -> int:
    current = store.load(job.job_id)
    if current.status in {"starting", "running"}:
        raise RescueError(f"job already has an active worker: {job.job_id}")
    store.transition(current, "starting")
    directory = store.root / job.job_id
    log = (directory / "worker.log").open("ab")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "fnos_rescue", "job-run", str(store.case), job.job_id],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        store.transition(current, "failed", error=str(exc))
        log.close()
        raise
    (directory / "worker.pid").write_text(f"{process.pid}\n")
    (directory / "worker.pid").chmod(0o600)
    (directory / "worker.log").chmod(0o600)
    store.append_event(job, "worker.started", {"pid": process.pid})
    log.close()
    return process.pid
