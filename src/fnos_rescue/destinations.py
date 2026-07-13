from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import SafetyError
from .runner import require_tool, run


NETWORK_FILESYSTEMS = {
    "nfs": "nfs",
    "nfs4": "nfs",
    "cifs": "smb",
    "smb3": "smb",
}
DEFAULT_DESTINATION_ROOTS = (Path("/mnt"), Path("/media"), Path("/run/media"), Path("/fs"))


@dataclass(frozen=True)
class DestinationFacts:
    path: str
    existing_ancestor: str
    source: str
    mountpoint: str
    filesystem: str
    kind: str
    read_only: bool
    writable: bool
    free_bytes: int
    total_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_filesystem(filesystem: str) -> str:
    return NETWORK_FILESYSTEMS.get(filesystem.lower(), "local")


def _approved_destination(path: str | Path, approved_roots: tuple[Path, ...] | None) -> Path:
    raw = os.fspath(path)
    if not raw or "\0" in raw:
        raise SafetyError("destination path is empty or contains a null byte")
    candidate = os.path.realpath(os.path.abspath(os.path.expanduser(raw)))
    roots = approved_roots
    if roots is None:
        configured = os.environ.get("FNOS_RESCUE_DESTINATION_ROOTS", "")
        roots = tuple(Path(value) for value in configured.split(":") if value.startswith("/"))
        if not roots:
            roots = DEFAULT_DESTINATION_ROOTS
    for root in roots:
        normalized_root = os.path.realpath(os.path.abspath(os.fspath(root)))
        prefix = normalized_root.rstrip(os.sep) + os.sep
        if candidate == normalized_root or candidate.startswith(prefix):
            return Path(candidate)
    raise SafetyError("destination is outside the administrator-approved recovery roots")


def _existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    if not current.exists() or not current.is_dir():
        raise SafetyError(f"destination has no existing directory ancestor: {path}")
    return current


def parse_findmnt(document: dict[str, Any]) -> tuple[str, str, str, tuple[str, ...]]:
    filesystems = document.get("filesystems") or []
    if len(filesystems) != 1:
        raise SafetyError("findmnt did not identify exactly one destination filesystem")
    entry = filesystems[0]
    options = tuple(str(entry.get("options") or "").split(","))
    return (
        str(entry.get("source") or "unknown"),
        str(entry.get("target") or "unknown"),
        str(entry.get("fstype") or "unknown"),
        options,
    )


def inspect_destination(
    path: str | Path, *, approved_roots: tuple[Path, ...] | None = None
) -> DestinationFacts:
    destination = _approved_destination(path, approved_roots)
    ancestor = _existing_ancestor(destination)
    if platform.system() != "Linux":
        raise SafetyError("destination mount inspection requires Linux")
    require_tool("findmnt")
    result = run(
        ["findmnt", "--json", "--output", "SOURCE,TARGET,FSTYPE,OPTIONS", "--target", ancestor]
    )
    source, mountpoint, filesystem, options = parse_findmnt(json.loads(result.stdout))
    usage = os.statvfs(ancestor)
    free_bytes = usage.f_bavail * usage.f_frsize
    total_bytes = usage.f_blocks * usage.f_frsize
    read_only = "ro" in options
    writable = not read_only and os.access(ancestor, os.W_OK | os.X_OK)
    return DestinationFacts(
        path=str(destination),
        existing_ancestor=str(ancestor),
        source=source,
        mountpoint=mountpoint,
        filesystem=filesystem,
        kind=classify_filesystem(filesystem),
        read_only=read_only,
        writable=writable,
        free_bytes=free_bytes,
        total_bytes=total_bytes,
    )


def assert_destination_ready(facts: DestinationFacts, required_bytes: int = 0) -> None:
    if facts.read_only or not facts.writable:
        raise SafetyError(f"destination is not writable: {facts.path}")
    if required_bytes < 0:
        raise SafetyError("required destination bytes cannot be negative")
    if facts.free_bytes < required_bytes:
        raise SafetyError(
            f"destination has insufficient space: need {required_bytes}, free {facts.free_bytes}"
        )
