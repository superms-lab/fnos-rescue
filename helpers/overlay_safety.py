"""Fail-closed proof that a writable target is a connected case-owned QCOW2 NBD."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path


NBD_DEVICE = re.compile(r"^/dev/nbd[0-9]+$")


def _resolved_backing(info: dict[str, object], overlay: Path) -> Path:
    value = info.get("full-backing-filename") or info.get("backing-filename")
    if not isinstance(value, str) or not value:
        raise RuntimeError("QCOW2 overlay has no backing device")
    path = Path(value)
    return (path if path.is_absolute() else overlay.parent / path).resolve()


def require_connected_case_overlay(device: str, state_file: str) -> dict[str, object]:
    if not NBD_DEVICE.fullmatch(device):
        raise RuntimeError("writable metadata target must be /dev/nbdN")
    state_path = Path(state_file).expanduser().resolve()
    if not state_path.is_file() or state_path.stat().st_mode & 0o077:
        raise RuntimeError("overlay state must be an existing private file")
    if state_path.stat().st_uid != os.geteuid():
        raise RuntimeError("overlay state is not owned by the current user")
    state = json.loads(state_path.read_text())
    required = {
        "state_version", "backing_device", "overlay", "overlay_device",
        "overlay_inode", "nbd_device", "nbd_pid", "connected",
    }
    if not required.issubset(state) or state.get("state_version") != 2:
        raise RuntimeError("overlay state is incomplete or obsolete")
    if state.get("connected") is not True or state.get("nbd_device") != device:
        raise RuntimeError("overlay state does not describe this connected NBD")

    target = Path(device)
    if not stat.S_ISBLK(target.stat().st_mode):
        raise RuntimeError("metadata target is not a block device")
    pid_file = Path("/sys/class/block") / target.name / "pid"
    try:
        active_pid = int(pid_file.read_text().strip())
    except (FileNotFoundError, ValueError) as exc:
        raise RuntimeError("NBD has no active qemu-nbd owner") from exc
    if active_pid <= 0 or active_pid != int(state["nbd_pid"]):
        raise RuntimeError("NBD owner changed after overlay connection")

    overlay = Path(str(state["overlay"])).resolve()
    overlay_stat = overlay.stat()
    if not overlay.is_file() or overlay.suffix != ".qcow2":
        raise RuntimeError("overlay artifact is missing or is not QCOW2")
    if overlay_stat.st_uid != os.geteuid():
        raise RuntimeError("overlay artifact is not owned by the current user")
    if (overlay_stat.st_dev, overlay_stat.st_ino) != (
        int(state["overlay_device"]), int(state["overlay_inode"]),
    ):
        raise RuntimeError("overlay artifact changed after connection")

    completed = subprocess.run(
        ["qemu-img", "info", "--output=json", str(overlay)],
        check=True, text=True, capture_output=True,
    )
    info = json.loads(completed.stdout)
    if info.get("format") != "qcow2":
        raise RuntimeError("overlay format is not qcow2")
    backing = _resolved_backing(info, overlay)
    if backing != Path(str(state["backing_device"])).resolve():
        raise RuntimeError("QCOW2 backing device does not match case state")
    if not stat.S_ISBLK(backing.stat().st_mode):
        raise RuntimeError("QCOW2 backing path is not a block device")
    readonly = subprocess.run(
        ["blockdev", "--getro", str(backing)],
        check=True, text=True, capture_output=True,
    ).stdout.strip()
    if readonly != "1":
        raise RuntimeError("QCOW2 backing source is not read-only")
    return state
