from __future__ import annotations

import json
import os
import subprocess
import sys
import fcntl
import hashlib
import stat
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .errors import RescueError
from .cases import assert_case_source
from .destinations import assert_destination_ready, inspect_destination
from .jobs import JobStore, RecoveryJob, _durable_text, _fsync_directory
from .safety import assert_destination_not_source
from .verify import iter_files, verify_file
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
    _durable_text(temporary, json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(target)
    _fsync_directory(target.parent)
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
        if step in completed:
            continue
        store.transition(job, "running", current_step=step)
        try:
            result = asdict(verify_file(candidate))
            results.append(result)
            _write_results(store, job, results)
            store.complete_step(job, step, {"sha256": result["sha256"]})
            if result["validation_ok"] is not True:
                store.record_failure(job, step, result["validation_error"] or "file is unvalidated")
                failures += 1
        except (OSError, ValueError) as exc:
            store.record_failure(job, step, str(exc))
            failures += 1
            continue
        completed.add(step)
    store.transition(job, "completed_with_errors" if failures or store.has_failures(job) else "completed")
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


def _open_directory_chain(root_fd: int, parts: tuple[str, ...], *, create: bool) -> int:
    descriptor = os.dup(root_fd)
    try:
        for part in parts:
            if part in {"", ".", ".."}:
                raise RescueError("unsafe directory component in copy path")
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            next_descriptor = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _hash_descriptor(descriptor: int, chunk_size: int = 4 << 20) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while block := os.read(descriptor, chunk_size):
        digest.update(block)
    return digest.hexdigest()


def _copy_relative_fd(source_root_fd: int, destination_root_fd: int, relative: Path, job_id: str) -> tuple[int, str]:
    parts = relative.parts
    if not parts:
        raise RescueError("copy path is empty")
    source_parent = _open_directory_chain(source_root_fd, parts[:-1], create=False)
    try:
        destination_parent = _open_directory_chain(destination_root_fd, parts[:-1], create=True)
    except Exception:
        os.close(source_parent)
        raise
    source_fd = -1
    temporary_fd = -1
    temporary_name = f".{parts[-1]}.{job_id}.tmp"
    try:
        source_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_parent)
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode):
            raise RescueError("copy source is no longer a regular file")
        try:
            target_stat = os.stat(parts[-1], dir_fd=destination_parent, follow_symlinks=False)
            if stat.S_ISLNK(target_stat.st_mode):
                raise RescueError("target symlink is not allowed")
            if not stat.S_ISREG(target_stat.st_mode):
                raise RescueError("copy target exists and is not a regular file")
        except FileNotFoundError:
            pass
        try:
            os.unlink(temporary_name, dir_fd=destination_parent)
        except FileNotFoundError:
            pass
        temporary_fd = os.open(
            temporary_name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=destination_parent,
        )
        digest = hashlib.sha256()
        copied = 0
        while block := os.read(source_fd, 4 << 20):
            digest.update(block)
            copied += len(block)
            view = memoryview(block)
            while view:
                written = os.write(temporary_fd, view)
                if written <= 0:
                    raise OSError("destination write made no progress")
                view = view[written:]
        after = os.fstat(source_fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ) or copied != before.st_size:
            raise RescueError("source changed while copying")
        os.fsync(temporary_fd)
        source_hash = digest.hexdigest()
        if _hash_descriptor(temporary_fd) != source_hash:
            raise RescueError("temporary destination reread checksum mismatch")
        os.close(temporary_fd)
        temporary_fd = -1
        os.replace(
            temporary_name,
            parts[-1],
            src_dir_fd=destination_parent,
            dst_dir_fd=destination_parent,
        )
        os.fsync(destination_parent)
        final_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=destination_parent)
        try:
            if _hash_descriptor(final_fd) != source_hash:
                raise RescueError("final destination reread checksum mismatch")
        finally:
            os.close(final_fd)
        return copied, source_hash
    finally:
        if temporary_fd >= 0:
            os.close(temporary_fd)
        try:
            os.unlink(temporary_name, dir_fd=destination_parent)
        except FileNotFoundError:
            pass
        if source_fd >= 0:
            os.close(source_fd)
        os.close(source_parent)
        os.close(destination_parent)


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
    selected_names = [relative.as_posix() for _source, relative in selected]
    if len(selected_names) != len(set(selected_names)):
        raise RescueError("copy selections contain duplicate file targets")
    required_bytes = sum(source.stat().st_size for source, _ in selected)
    destination_facts = inspect_destination(destination)
    assert_destination_not_source(source_device, destination_facts.existing_ancestor)
    assert_destination_ready(destination_facts, required_bytes)
    destination.mkdir(parents=True, exist_ok=True)

    failures = 0
    source_root_fd = os.open(source_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    destination_root_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for _source, relative in selected:
            if _apply_control(store, job):
                return job
            step = relative.as_posix()
            if step in job.completed_steps:
                continue
            target = destination / relative
            _assert_safe_target(destination, target)
            store.transition(job, "running", current_step=step)
            try:
                copied, target_hash = _copy_relative_fd(
                    source_root_fd, destination_root_fd, relative, job.job_id
                )
                store.complete_step(
                    job,
                    step,
                    {"sha256": target_hash, "bytes": copied, "destination": str(target)},
                )
            except (OSError, RescueError) as exc:
                store.record_failure(job, step, str(exc))
                failures += 1
    finally:
        os.close(source_root_fd)
        os.close(destination_root_fd)
    store.transition(job, "completed_with_errors" if failures or store.has_failures(job) else "completed")
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
        for parameter in ("device", "source_device", "backing_device"):
            if parameter in job.parameters:
                assert_case_source(store.case, str(job.parameters[parameter]))
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


def _worker_is_alive(directory: Path, job_id: str) -> bool:
    pid_path = directory / "worker.pid"
    try:
        pid = int(pid_path.read_text().strip())
        if pid <= 1:
            return False
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return False
    command_line = Path(f"/proc/{pid}/cmdline")
    if command_line.is_file():
        try:
            return job_id.encode() in command_line.read_bytes().split(b"\0")
        except OSError:
            return False
    return True


def start_background(store: JobStore, job: RecoveryJob) -> int:
    current = store.load(job.job_id)
    directory = store.root / job.job_id
    if current.status in {"starting", "running"}:
        if _worker_is_alive(directory, job.job_id):
            raise RescueError(f"job already has an active worker: {job.job_id}")
        store.append_event(current, "worker.stale", {"previous_status": current.status})
    store.transition(current, "starting")
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
    _durable_text(directory / "worker.pid", f"{process.pid}\n")
    _fsync_directory(directory)
    (directory / "worker.log").chmod(0o600)
    store.append_event(job, "worker.started", {"pid": process.pid})
    log.close()
    return process.pid
