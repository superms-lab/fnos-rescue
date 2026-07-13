from __future__ import annotations

import json
from pathlib import Path

from .devices import (
    DeviceFacts,
    current_read_only,
    find_serial,
    inspect_device,
    is_root,
    related_block_devices,
    related_block_identities,
)
from .errors import SafetyError
from .runner import require_tool, run


FORBIDDEN_SOURCE_COMMANDS = (
    "btrfs check --repair",
    "btrfs rescue zero-log",
    "btrfs rescue fix-device-size",
    "mdadm --create",
    "mkfs",
)


def confirm_serial(facts: DeviceFacts, supplied: str) -> str:
    actual = find_serial(facts)
    if not actual:
        raise SafetyError("device has no stable serial; refuse mutating device state")
    if supplied.strip() != actual:
        raise SafetyError(f"serial confirmation mismatch: expected {actual!r}")
    return actual


def protect_source(
    device: str | Path,
    *,
    confirmed_serial: str,
    dry_run: bool = False,
) -> list[str]:
    facts = inspect_device(device)
    confirm_serial(facts, confirmed_serial)
    if not is_root() and not dry_run:
        raise SafetyError("protect requires root privileges")
    require_tool("blockdev")
    paths = related_block_devices(device)
    _assert_no_writable_mounts(paths)
    if dry_run:
        return [f"blockdev --setro {path}" for path in paths]
    for _ in range(2):
        for path in paths:
            run(["blockdev", "--setro", path])
    failed = [path for path in paths if not current_read_only(path)]
    if failed:
        raise SafetyError(f"read-only verification failed: {', '.join(failed)}")
    return paths


def assert_read_only(path: str | Path) -> None:
    if not current_read_only(path):
        raise SafetyError(f"source layer is writable: {path}")


def assert_source_graph_read_only(path: str | Path) -> list[str]:
    paths = related_block_devices(path)
    _assert_no_writable_mounts(paths)
    writable = [device for device in paths if not current_read_only(device)]
    if writable:
        raise SafetyError(f"source device graph is writable: {', '.join(writable)}")
    return paths


def destination_source(path: str | Path) -> str | None:
    require_tool("findmnt")
    destination = Path(path).expanduser().resolve()
    result = run(
        ["findmnt", "--evaluate", "--noheadings", "--output", "SOURCE", "--target", destination],
        check=False,
    )
    return result.stdout.strip() or None


def assert_destination_not_source(source: str | Path, destination: str | Path) -> None:
    mounted_from = destination_source(destination)
    if not mounted_from:
        raise SafetyError(f"cannot identify destination filesystem: {destination}")
    mounted_device = mounted_from.split("[", 1)[0]
    if not mounted_device.startswith("/dev/"):
        filesystem = run(
            ["findmnt", "--noheadings", "--output", "FSTYPE", "--target", Path(destination).resolve()],
            check=False,
        ).stdout.strip().lower()
        if filesystem in {"nfs", "nfs4", "cifs", "smb3"}:
            return
        raise SafetyError(
            f"cannot prove physical separation for destination source {mounted_from!r} ({filesystem or 'unknown'})"
        )
    source_ids = related_block_identities(source)
    destination_ids = related_block_identities(mounted_device)
    if source_ids & destination_ids:
        raise SafetyError("destination resolves to the source disk or one of its layers")


def _assert_no_writable_mounts(paths: list[str]) -> None:
    require_tool("findmnt")
    for path in paths:
        result = run(
            ["findmnt", "--json", "--output", "SOURCE,TARGET,OPTIONS", "--source", path],
            check=False,
        )
        if not result.stdout.strip():
            continue
        try:
            filesystems = json.loads(result.stdout).get("filesystems") or []
        except ValueError as exc:
            raise SafetyError(f"cannot verify mount state for source layer: {path}") from exc
        for filesystem in filesystems:
            options = set(str(filesystem.get("options") or "").split(","))
            if "rw" in options:
                target = filesystem.get("target") or "unknown"
                raise SafetyError(f"source layer is mounted read-write: {path} at {target}")
