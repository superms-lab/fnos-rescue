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
            "NAME,PATH,SIZE,RO,TYPE,FSTYPE,MODEL,SERIAL,UUID,MOUNTPOINTS",
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


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0
