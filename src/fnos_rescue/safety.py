from __future__ import annotations

from pathlib import Path

from .devices import (
    DeviceFacts,
    current_read_only,
    find_serial,
    inspect_device,
    is_root,
    iter_device_paths,
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
    paths = list(iter_device_paths(facts))
    if dry_run:
        return [f"blockdev --setro {path}" for path in paths]
    for path in paths:
        run(["blockdev", "--setro", path])
    failed = [path for path in paths if not current_read_only(path)]
    if failed:
        raise SafetyError(f"read-only verification failed: {', '.join(failed)}")
    return paths


def assert_read_only(path: str | Path) -> None:
    if not current_read_only(path):
        raise SafetyError(f"source layer is writable: {path}")


def destination_source(path: str | Path) -> str | None:
    require_tool("findmnt")
    destination = Path(path).expanduser().resolve()
    result = run(
        ["findmnt", "--noheadings", "--output", "SOURCE", "--target", destination],
        check=False,
    )
    return result.stdout.strip() or None


def assert_destination_not_source(source: str | Path, destination: str | Path) -> None:
    mounted_from = destination_source(destination)
    if not mounted_from:
        raise SafetyError(f"cannot identify destination filesystem: {destination}")
    source_name = Path(source).name
    result = run(["lsblk", "--noheadings", "--output", "NAME,PKNAME", mounted_from], check=False)
    names = {part for line in result.stdout.splitlines() for part in line.split()}
    if source_name in names or str(Path(source)) == mounted_from:
        raise SafetyError("destination resolves to the source disk or one of its layers")
