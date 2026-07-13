from __future__ import annotations

import json
import re
import base64
import binascii
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .cases import RecoveryCase
from .devices import require_block_device
from .errors import JobControlRequested, RescueError
from .jobs import JobStore, RecoveryJob, _durable_text, _fsync_directory
from .plugins.fnos_btrfs import FnosBtrfsPlugin
from .runner import run_interruptible, run_streaming
from .safety import assert_read_only
from .verify import sha256_file, verify_file


FSID = re.compile(r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$")
ROOT_LINE = re.compile(
    r"^(?P<kind>ROOT_TREE|FS_CANDIDATE)\s+physical=(?P<physical>\d+)\s+"
    r"logical=(?P<logical>\d+)\s+generation=(?P<generation>\d+)\s+"
    r"(?:owner=(?P<owner>\d+)\s+)?nritems=(?P<nritems>\d+)\s+level=(?P<level>\d+)\s*$"
)
MAX_ROOT_CANDIDATES = 250_000
TRUSTED_TOOL_ROOTS = (
    Path("/usr/lib/fnos-rescue/bin"),
    Path("/var/apps/fnos-rescue/bin"),
    Path("/opt/fnos-rescue/bin"),
)


def _trusted_tool(parameters: dict[str, Any], parameter: str, filename: str) -> Path:
    supplied = str(parameters.get(parameter, "")).strip()
    candidates = [Path(supplied)] if supplied else [root / filename for root in TRUSTED_TOOL_ROOTS]
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if not resolved.is_file() or not resolved.stat().st_mode & 0o111:
            continue
        if any(resolved == (root / filename).resolve() for root in TRUSTED_TOOL_ROOTS):
            return resolved
    if supplied:
        raise RescueError(f"{parameter} must be the packaged trusted tool: {filename}")
    raise RescueError(f"packaged recovery tool is missing: {filename}")


def _job_directory(store: JobStore, job: RecoveryJob) -> Path:
    return store.root / job.job_id


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    _durable_text(temporary, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)
    _fsync_directory(path.parent)


def _normalize_fsid(value: object) -> str:
    fsid = str(value or "").strip().lower().replace("-", "")
    if not re.fullmatch(r"[0-9a-f]{32}", fsid):
        raise RescueError("a valid Btrfs FSID is required for evidence binding")
    return fsid


def _parse_root_candidates(output: str | Iterable[str], fsid: object) -> list[dict[str, Any]]:
    normalized_fsid = _normalize_fsid(fsid)
    grouped: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    lines = output.splitlines() if isinstance(output, str) else output
    for line in lines:
        match = ROOT_LINE.fullmatch(line.strip())
        if match is None:
            continue
        values = match.groupdict()
        owner = int(values["owner"] or 1)
        key = (int(values["logical"]), int(values["generation"]), owner, int(values["level"]))
        if key not in grouped and len(grouped) >= MAX_ROOT_CANDIDATES:
            raise RescueError("root scan exceeded the safe candidate limit; narrow the scan range")
        candidate = grouped.setdefault(
            key,
            {
                "fsid": normalized_fsid,
                "logical": key[0],
                "generation": key[1],
                "owner": key[2],
                "level": key[3],
                "nritems": int(values["nritems"]),
                "kind": "root_tree" if values["kind"] == "ROOT_TREE" else "filesystem_tree",
                "physical_copies": [],
            },
        )
        physical = int(values["physical"])
        if physical not in candidate["physical_copies"]:
            candidate["physical_copies"].append(physical)
    return sorted(grouped.values(), key=lambda item: (item["owner"], -item["generation"], item["logical"]))


def _case_source(store: JobStore) -> dict[str, Any]:
    case = RecoveryCase.load(store.case)
    source = case.source
    required = {"path", "serial", "size_bytes"}
    if not required.issubset(source) or not source.get("serial") or int(source.get("size_bytes") or 0) <= 0:
        raise RescueError("recovery case has incomplete source identity; recreate the case")
    return source


def _cache_manifest_path(cache: Path) -> Path:
    return cache.with_name(cache.name + ".manifest.json")


def _required_cache(store: JobStore, parameters: dict[str, Any], tool: Path, device: Path) -> tuple[Path, dict[str, Any]]:
    cache = _required_file(parameters, "chunk_cache")
    try:
        relative = cache.relative_to(store.root.resolve())
    except ValueError as exc:
        raise RescueError("chunk_cache must be an artifact owned by this recovery case") from exc
    if len(relative.parts) != 2 or relative.parts[1] != "chunk-mappings.cache":
        raise RescueError("chunk_cache path is not a canonical case cache artifact")
    owner_job = store.load(relative.parts[0])
    if owner_job.kind != "btrfs-chunk-cache" or owner_job.status != "completed":
        raise RescueError("chunk_cache owner is not a completed cache job")
    manifest_path = _cache_manifest_path(cache)
    if not manifest_path.is_file():
        raise RescueError("chunk cache provenance manifest is missing")
    manifest = json.loads(manifest_path.read_text())
    source = _case_source(store)
    if manifest.get("schema_version") != 1 or manifest.get("case_id") != RecoveryCase.load(store.case).case_id:
        raise RescueError("chunk cache manifest does not belong to this recovery case")
    if manifest.get("cache", {}).get("sha256") != sha256_file(cache) or manifest.get("cache", {}).get("bytes") != cache.stat().st_size:
        raise RescueError("chunk cache content no longer matches its manifest")
    manifest_source = manifest.get("source", {})
    for key in ("serial", "size_bytes"):
        if manifest_source.get(key) != source.get(key):
            raise RescueError(f"chunk cache source {key} no longer matches the case")
    if manifest.get("recovery_layer") != str(device.resolve()):
        raise RescueError("chunk cache was generated from a different recovery layer")
    if manifest.get("tool", {}).get("sha256") != sha256_file(tool):
        raise RescueError("private btrfs tool differs from the cache-producing binary")
    if manifest.get("tool", {}).get("package_version") != __version__:
        raise RescueError("chunk cache was produced by a different FNOS Rescue version")
    _normalize_fsid(manifest.get("fsid"))
    return cache, manifest


def _candidate_from_value(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    required = {"fsid", "logical", "generation", "owner", "level"}
    if not required.issubset(value):
        return None
    return {
        **value,
        "fsid": _normalize_fsid(value["fsid"]),
        "logical": int(value["logical"]),
        "generation": int(value["generation"]),
        "owner": int(value["owner"]),
        "level": int(value["level"]),
    }


def _root_evidence(
    store: JobStore,
    parameters: dict[str, Any],
    parameter: str,
    logical: int,
    owner: int,
    fsid: str,
) -> dict[str, Any]:
    selection = _candidate_from_value(parameters.get(f"{parameter}_evidence"))
    candidates: list[dict[str, Any]] = []
    for path in store.root.glob("job-*/root-candidates.json"):
        try:
            owner_job = store.load(path.parent.name)
            if owner_job.kind != "btrfs-root-scan" or owner_job.status != "completed":
                continue
            scan_summary = json.loads((path.parent / "root-scan.json").read_text())
            if scan_summary.get("candidate_sha256") != sha256_file(path):
                continue
            payload = json.loads(path.read_text())
            candidates.extend(filter(None, (_candidate_from_value(item) for item in payload.get("candidates", []))))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    matches = [
        item for item in candidates
        if item["logical"] == logical and item["owner"] == owner and item["fsid"] == fsid
    ]
    if selection is not None:
        matches = [
            item for item in matches
            if item["generation"] == selection["generation"] and item["level"] == selection["level"]
        ]
    identities = {(item["generation"], item["level"]) for item in matches}
    if not matches:
        raise RescueError(f"{parameter} has no matching root-scan evidence for owner {owner}")
    if len(identities) != 1:
        raise RescueError(f"{parameter} evidence is ambiguous; select a generation and level explicitly")
    evidence = matches[0]
    if evidence["generation"] <= 0 or not 0 <= evidence["level"] <= 7:
        raise RescueError(f"{parameter} evidence has invalid generation or level")
    return evidence


def _forced_root_environment(prefix: str, evidence: dict[str, Any]) -> dict[str, str]:
    return {
        prefix: str(evidence["logical"]),
        f"{prefix}_FSID": evidence["fsid"],
        f"{prefix}_OWNER": str(evidence["owner"]),
        f"{prefix}_GENERATION": str(evidence["generation"]),
        f"{prefix}_LEVEL": str(evidence["level"]),
    }


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
    scanner = _trusted_tool(parameters, "scanner", "scan_btrfs_roots")
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
    directory = _job_directory(store, job)
    log = directory / "root-scan.log"
    errors = directory / "root-scan.stderr.log"
    result = run_streaming(
        argv,
        timeout=float(job.parameters.get("timeout", 86400)),
        stdout_path=log,
        stderr_path=errors,
    )
    log.chmod(0o600)
    errors.chmod(0o600)
    with log.open(errors="replace") as lines:
        candidates = _parse_root_candidates(lines, job.parameters.get("fsid"))
    candidate_artifact = directory / "root-candidates.json"
    _write_json(
        candidate_artifact,
        {
            "schema_version": 1,
            "fsid": _normalize_fsid(job.parameters.get("fsid")),
            "scanner_sha256": sha256_file(Path(argv[0])),
            "candidates": candidates,
        },
    )
    summary = {
        "argv": list(result.argv),
        "returncode": result.returncode,
        "stdout_bytes": log.stat().st_size,
        "stderr_bytes": errors.stat().st_size,
        "artifact": str(log),
        "candidate_artifact": str(candidate_artifact),
        "candidate_count": len(candidates),
        "candidate_sha256": sha256_file(candidate_artifact),
    }
    _write_json(directory / "root-scan.json", summary)
    store.complete_step(job, "scan-historical-roots", summary)
    store.transition(job, "completed")
    return job


def _private_btrfs(parameters: dict[str, Any]) -> Path:
    return _trusted_tool(parameters, "private_btrfs", "fnos-rescue-btrfs")


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
    fsid = _normalize_fsid(job.parameters.get("fsid"))
    cache = _job_directory(store, job) / "chunk-mappings.cache"
    store.transition(job, "running", current_step="build-chunk-cache")
    directory = _job_directory(store, job)
    stdout_log = directory / "chunk-cache.stdout.log"
    stderr_log = directory / "chunk-cache.stderr.log"
    run_streaming(
        [tool, "rescue", "chunk-recover", "-y", device],
        timeout=float(job.parameters.get("timeout", 86400)),
        env={"BTRFS_CHUNK_CACHE_SAVE": str(cache), "BTRFS_CHUNK_CACHE_ONLY": "1"},
        stdout_path=stdout_log,
        stderr_path=stderr_log,
    )
    if not cache.is_file() or cache.stat().st_size == 0:
        raise RescueError("private btrfs tool did not create a non-empty chunk cache")
    cache.chmod(0o600)
    case = RecoveryCase.load(store.case)
    source = _case_source(store)
    manifest = {
        "schema_version": 1,
        "case_id": case.case_id,
        "fsid": fsid,
        "source": {
            "path": source["path"],
            "serial": source["serial"],
            "size_bytes": source["size_bytes"],
            "uuid": source.get("uuid"),
        },
        "recovery_layer": str(device.resolve()),
        "cache": {"path": str(cache), "bytes": cache.stat().st_size, "sha256": sha256_file(cache)},
        "tool": {"path": str(tool), "sha256": sha256_file(tool), "package_version": __version__},
    }
    manifest_path = _cache_manifest_path(cache)
    _write_json(manifest_path, manifest)
    stdout_log.chmod(0o600)
    stderr_log.chmod(0o600)
    details = {
        "artifact": str(cache),
        "manifest": str(manifest_path),
        "bytes": cache.stat().st_size,
        "sha256": manifest["cache"]["sha256"],
        "fsid": fsid,
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
    }
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
    cache, cache_manifest = _required_cache(store, job.parameters, tool, device)
    fs_root = _positive_integer(job.parameters, "filesystem_root")
    fsid = _normalize_fsid(cache_manifest["fsid"])
    root_evidence = _root_evidence(store, job.parameters, "filesystem_root", fs_root, 5, fsid)
    inventory = _job_directory(store, job) / "btrfs-files.tsv"
    store.transition(job, "running", current_step="list-filesystem-tree")
    directory = _job_directory(store, job)
    stdout_log = directory / "list.stdout.log"
    stderr_log = directory / "list.stderr.log"
    run_streaming(
        [tool, "rescue", "chunk-recover", "-y", device],
        timeout=float(job.parameters.get("timeout", 3600)),
        env={
            "BTRFS_CHUNK_CACHE_LOAD": str(cache),
            "BTRFS_LIST_PATHS": str(inventory),
            **_forced_root_environment("BTRFS_FORCE_FS_ROOT", root_evidence),
        },
        stdout_path=stdout_log,
        stderr_path=stderr_log,
    )
    if not inventory.is_file() or inventory.stat().st_size == 0:
        raise RescueError("private btrfs tool did not create a file inventory")
    inventory.chmod(0o600)
    stdout_log.chmod(0o600)
    stderr_log.chmod(0o600)
    details = {
        "artifact": str(inventory), "bytes": inventory.stat().st_size,
        "stdout_log": str(stdout_log), "stderr_log": str(stderr_log),
        "root_evidence": root_evidence, "chunk_cache_sha256": cache_manifest["cache"]["sha256"],
    }
    store.complete_step(job, "list-filesystem-tree", details)
    store.transition(job, "completed")
    return job


def execute_btrfs_extract_inode(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    device = _readonly_device(job.parameters)
    tool = _private_btrfs(job.parameters)
    cache, cache_manifest = _required_cache(store, job.parameters, tool, device)
    fs_root = _positive_integer(job.parameters, "filesystem_root")
    rootid = _positive_integer(job.parameters, "rootid")
    inode = _positive_integer(job.parameters, "inode")
    output = _job_directory(store, job) / "extracted.bin"
    output.unlink(missing_ok=True)
    fsid = _normalize_fsid(cache_manifest["fsid"])
    root_evidence = _root_evidence(store, job.parameters, "filesystem_root", fs_root, 5, fsid)
    environment = {
        "BTRFS_CHUNK_CACHE_LOAD": str(cache),
        "BTRFS_EXTRACT_ROOTID": str(rootid),
        "BTRFS_EXTRACT_INODE": str(inode),
        "BTRFS_EXTRACT_PATH": str(output),
        **_forced_root_environment("BTRFS_FORCE_FS_ROOT", root_evidence),
    }
    historical_root = job.parameters.get("historical_root")
    if historical_root is not None:
        historical_root = int(historical_root)
        historical_evidence = _root_evidence(
            store, job.parameters, "historical_root", historical_root, rootid, fsid
        )
        environment.update(_forced_root_environment("BTRFS_FORCE_EXTRACT_ROOT", historical_evidence))
    store.transition(job, "running", current_step="extract-inode")
    directory = _job_directory(store, job)
    stdout_log = directory / "extract.stdout.log"
    stderr_log = directory / "extract.stderr.log"
    run_streaming(
        [tool, "rescue", "chunk-recover", "-y", device],
        timeout=float(job.parameters.get("timeout", 3600)),
        env=environment,
        stdout_path=stdout_log,
        stderr_path=stderr_log,
    )
    if not output.is_file():
        raise RescueError("private btrfs tool did not create an extracted file")
    expected_size_value = job.parameters.get("expected_size")
    expected_size = int(expected_size_value) if expected_size_value is not None else None
    verification = verify_file(
        output,
        expected_size=expected_size,
        expected_sha256=job.parameters.get("expected_sha256"),
        expected_empty=expected_size == 0,
    )
    output.chmod(0o600)
    stdout_log.chmod(0o600)
    stderr_log.chmod(0o600)
    details = {
        "artifact": str(output), "bytes": output.stat().st_size,
        "stdout_log": str(stdout_log), "stderr_log": str(stderr_log),
        "verification": asdict(verification), "root_evidence": root_evidence,
    }
    store.complete_step(job, "extract-inode", details)
    if verification.validation_ok is True:
        store.transition(job, "completed")
    else:
        store.record_failure(job, "extract-inode", verification.validation_error or "file is unvalidated")
        store.transition(job, "completed_with_errors")
    return job


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise RescueError(f"extraction path must be relative and contained: {value}")
    return path


def _item_relative(item: dict[str, Any]) -> tuple[Path, str, str]:
    encoded = str(item.get("path_b64") or "")
    if encoded:
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise RescueError("extraction path_b64 is invalid") from exc
        if not raw or raw.startswith(b"/") or b"\0" in raw:
            raise RescueError("extraction path bytes are unsafe")
        parts = raw.split(b"/")
        if any(part in {b"", b".."} for part in parts):
            raise RescueError("extraction path bytes escape the output root")
        relative = _safe_relative(os.fsdecode(raw))
        display = str(item.get("path") or encoded)
        return relative, encoded, display
    display = str(item.get("path", ""))
    relative = _safe_relative(display)
    encoded = base64.b64encode(os.fsencode(relative.as_posix())).decode("ascii")
    return relative, encoded, display


def execute_btrfs_extract_batch(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    device = _readonly_device(job.parameters)
    tool = _private_btrfs(job.parameters)
    cache, cache_manifest = _required_cache(store, job.parameters, tool, device)
    fs_root = _positive_integer(job.parameters, "filesystem_root")
    fsid = _normalize_fsid(cache_manifest["fsid"])
    root_evidence = _root_evidence(store, job.parameters, "filesystem_root", fs_root, 5, fsid)
    items = job.parameters.get("items")
    if not isinstance(items, list) or not items:
        raise RescueError("batch extraction requires a non-empty items list")
    output_root = _job_directory(store, job) / "extracted"
    output_root.mkdir(mode=0o700, exist_ok=True)
    failures = 0
    results: list[dict[str, Any]] = []
    seen_identities: set[str] = set()
    seen_targets: set[bytes] = set()
    for item in items:
        if not isinstance(item, dict):
            raise RescueError("each extraction item must be an object")
        rootid = int(item.get("rootid", 0))
        inode = int(item.get("inode", 0))
        expected_size = int(item.get("expected_size", -1))
        if item.get("type") not in {None, "", 1, "1"}:
            raise RescueError("batch extraction accepts regular files only")
        if rootid <= 0 or inode <= 0 or expected_size < 0:
            raise RescueError("invalid extraction rootid, inode, or expected_size")
        relative, path_token, display_path = _item_relative(item)
        step = f"{rootid}:{inode}:{path_token}"
        target_identity = os.fsencode(relative.as_posix())
        if step in seen_identities or target_identity in seen_targets:
            raise RescueError(f"duplicate extraction identity or target: {display_path}")
        seen_identities.add(step)
        seen_targets.add(target_identity)
        if step in job.completed_steps:
            continue
        action = store.requested_action(job)
        if action in {"pause", "cancel"}:
            store.transition(job, "paused" if action == "pause" else "cancelled")
            return job
        target = output_root / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.unlink(missing_ok=True)
        environment = {
            "BTRFS_CHUNK_CACHE_LOAD": str(cache),
            "BTRFS_EXTRACT_ROOTID": str(rootid),
            "BTRFS_EXTRACT_INODE": str(inode),
            "BTRFS_EXTRACT_PATH": str(target),
            **_forced_root_environment("BTRFS_FORCE_FS_ROOT", root_evidence),
        }
        if item.get("historical_root") is not None:
            historical_root = int(item["historical_root"])
            historical_evidence = _root_evidence(
                store,
                {**job.parameters, "historical_root_evidence": item.get("historical_root_evidence")},
                "historical_root",
                historical_root,
                rootid,
                fsid,
            )
            environment.update(_forced_root_environment("BTRFS_FORCE_EXTRACT_ROOT", historical_evidence))
        store.transition(job, "running", current_step=step)
        try:
            run_interruptible(
                [tool, "rescue", "chunk-recover", "-y", device],
                timeout=float(job.parameters.get("per_file_timeout", 3600)),
                env=environment,
                control=lambda: store.requested_action(job),
                stdout_path=_job_directory(store, job) / "extract.stdout.log",
                stderr_path=_job_directory(store, job) / "extract.stderr.log",
                append=True,
            )
            if not target.is_file():
                raise RescueError("private btrfs tool did not create the requested file")
            verification = verify_file(
                target,
                expected_size=expected_size,
                expected_sha256=item.get("expected_sha256"),
                expected_empty=expected_size == 0,
            )
            target.chmod(0o600)
            result = {
                "identity": step,
                "path": display_path,
                "path_b64": path_token,
                "rootid": rootid,
                "inode": inode,
                "bytes": target.stat().st_size,
                "sha256": verification.sha256,
                "artifact": str(target),
                "verification": asdict(verification),
            }
            results.append(result)
            store.complete_step(job, step, result)
            if verification.validation_ok is not True:
                store.record_failure(job, step, verification.validation_error or "file is unvalidated")
                failures += 1
        except JobControlRequested as exc:
            target.unlink(missing_ok=True)
            store.transition(job, "paused" if exc.action == "pause" else "cancelled", current_step=step)
            return job
        except (OSError, RescueError, ValueError) as exc:
            store.record_failure(job, step, str(exc))
            failures += 1
    _write_json(_job_directory(store, job) / "batch-results.json", results)
    store.transition(job, "completed_with_errors" if failures or store.has_failures(job) else "completed")
    return job
