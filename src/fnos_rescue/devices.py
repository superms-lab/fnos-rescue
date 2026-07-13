from __future__ import annotations

import json
import os
import platform
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from .errors import RescueError, SafetyError
from .runner import require_tool, run


@dataclass(frozen=True)
class DeviceFacts:
    path: str
    name: str
    size_bytes: int
    read_only: bool
    device_type: str
    filesystem: str | None
    model: str | None
    serial: str | None
    uuid: str | None
    mountpoints: tuple[str, ...]
    major_minor: str | None = None
    parent_name: str | None = None
    children: tuple["DeviceFacts", ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def require_linux() -> None:
    if platform.system() != "Linux":
        raise SafetyError(
            "raw-device operations require Linux; use the FNOS Rescue Live environment"
        )


def require_block_device(path: str | Path) -> Path:
    require_linux()
    resolved = Path(path).resolve()
    try:
        mode = resolved.stat().st_mode
    except FileNotFoundError as exc:
        raise SafetyError(f"device does not exist: {resolved}") from exc
    if not stat.S_ISBLK(mode):
        raise SafetyError(f"not a block device: {resolved}")
    return resolved


def _walk(entries: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for entry in entries:
        yield entry
        yield from _walk(entry.get("children") or [])


def _mountpoints(entry: dict[str, Any]) -> tuple[str, ...]:
    points = entry.get("mountpoints") or []
    return tuple(str(point) for point in points if point)


def _from_lsblk(entry: dict[str, Any]) -> DeviceFacts:
    return DeviceFacts(
        path=str(entry.get("path") or f"/dev/{entry['name']}"),
        name=str(entry["name"]),
        size_bytes=int(entry.get("size") or 0),
        read_only=bool(int(entry.get("ro") or 0)),
        device_type=str(entry.get("type") or "unknown"),
        filesystem=entry.get("fstype"),
        model=(entry.get("model") or "").strip() or None,
        serial=(entry.get("serial") or "").strip() or None,
        uuid=entry.get("uuid"),
        mountpoints=_mountpoints(entry),
        major_minor=str(entry.get("maj:min") or "") or None,
        parent_name=str(entry.get("pkname") or "") or None,
        children=tuple(_from_lsblk(child) for child in entry.get("children") or []),
    )


def inspect_device(path: str | Path) -> DeviceFacts:
    device = require_block_device(path)
    require_tool("lsblk")
    result = run(
        [
            "lsblk",
            "--json",
            "--bytes",
            "--output",
            "NAME,PATH,SIZE,RO,TYPE,FSTYPE,MODEL,SERIAL,UUID,MOUNTPOINTS,MAJ:MIN,PKNAME",
        ]
    )
    document = json.loads(result.stdout)
    candidates = list(_walk(document.get("blockdevices") or []))
    for candidate in candidates:
        candidate_path = Path(candidate.get("path") or f"/dev/{candidate['name']}")
        if candidate_path.resolve() == device:
            return _from_lsblk(candidate)
    raise RescueError(f"lsblk did not return device facts for {device}")


def iter_device_paths(facts: DeviceFacts) -> Iterator[str]:
    for child in facts.children:
        yield from iter_device_paths(child)
    yield facts.path


def find_serial(facts: DeviceFacts) -> str | None:
    if facts.serial:
        return facts.serial
    for child in facts.children:
        serial = find_serial(child)
        if serial:
            return serial
    return None


def current_read_only(path: str | Path) -> bool:
    require_tool("blockdev")
    result = run(["blockdev", "--getro", str(path)])
    return result.stdout.strip() == "1"


def block_identity(path: str | Path) -> str:
    """Return the kernel major:minor identity for a real block device."""
    device = require_block_device(path)
    value = device.stat().st_rdev
    return f"{os.major(value)}:{os.minor(value)}"


def _sysfs_neighbors(node: Path) -> Iterator[Path]:
    for relation in ("holders", "slaves"):
        directory = node / relation
        if directory.is_dir():
            for linked in directory.iterdir():
                try:
                    yield linked.resolve(strict=True)
                except FileNotFoundError:
                    continue
    if (node / "partition").is_file():
        parent = node.parent
        if (parent / "dev").is_file():
            yield parent
    else:
        for child in node.iterdir():
            if child.is_dir() and (child / "partition").is_file():
                yield child.resolve()


def related_block_devices(
    path: str | Path,
    *,
    sys_dev_block: Path = Path("/sys/dev/block"),
    dev_root: Path = Path("/dev"),
) -> list[str]:
    """Return every partition/holder/slave in the source's kernel device graph.

    The graph is deliberately traversed in both directions.  This protects a
    whole disk, its partitions, and any active MD/LVM/loop holders together.
    """
    identity = block_identity(path)
    entry = sys_dev_block / identity
    try:
        start = entry.resolve(strict=True)
    except FileNotFoundError as exc:
        raise SafetyError(f"kernel device graph is missing for {path}: {identity}") from exc
    pending = [start]
    seen: set[Path] = set()
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        pending.extend(neighbor for neighbor in _sysfs_neighbors(node) if neighbor not in seen)
    paths = []
    for node in seen:
        dev = node / "dev"
        if not dev.is_file():
            raise SafetyError(f"kernel device graph node has no identity: {node}")
        candidate = dev_root / node.name
        if not candidate.exists():
            raise SafetyError(f"kernel device graph node has no device path: {candidate}")
        paths.append(str(candidate.resolve()))
    return sorted(set(paths))


def related_block_identities(path: str | Path) -> set[str]:
    return {block_identity(device) for device in related_block_devices(path)}


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0
