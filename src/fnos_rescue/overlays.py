from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .devices import require_block_device
from .errors import RescueError
from .jobs import JobStore, RecoveryJob
from .runner import require_tool, run
from .safety import assert_read_only


NBD_DEVICE = re.compile(r"^/dev/nbd[0-9]+$")


def _write_state(store: JobStore, job: RecoveryJob, state: dict[str, Any]) -> Path:
    target = store.root / job.job_id / "overlay-state.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(target)
    return target


def _overlay_backing(overlay: Path) -> Path:
    result = run(["qemu-img", "info", "--output=json", overlay])
    info = json.loads(result.stdout)
    if info.get("format") != "qcow2":
        raise RescueError("overlay format is not qcow2")
    value = info.get("full-backing-filename") or info.get("backing-filename")
    if not isinstance(value, str) or not value:
        raise RescueError("overlay has no backing device")
    backing = Path(value)
    backing = (backing if backing.is_absolute() else overlay.parent / backing).resolve()
    backing = require_block_device(backing)
    assert_read_only(backing)
    return backing


def _nbd_pid(nbd: str) -> int:
    try:
        pid = int((Path("/sys/class/block") / Path(nbd).name / "pid").read_text().strip())
    except (FileNotFoundError, ValueError) as exc:
        raise RescueError(f"connected NBD has no qemu-nbd owner: {nbd}") from exc
    if pid <= 0:
        raise RescueError(f"connected NBD has invalid qemu-nbd owner: {nbd}")
    return pid


def execute_overlay_create(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    backing = require_block_device(str(job.parameters.get("backing_device", "")))
    assert_read_only(backing)
    require_tool("qemu-img")
    overlay = store.root / job.job_id / "recovery-overlay.qcow2"
    overlay.unlink(missing_ok=True)
    store.transition(job, "running", current_step="create-overlay")
    run(["qemu-img", "create", "-f", "qcow2", "-F", "raw", "-b", backing, overlay])
    if not overlay.is_file() or overlay.stat().st_size == 0:
        raise RescueError("qemu-img did not create a QCOW2 overlay")
    overlay.chmod(0o600)
    state = {"backing_device": str(backing), "overlay": str(overlay), "nbd_device": None}
    state_path = _write_state(store, job, state)
    store.complete_step(job, "create-overlay", {"artifact": str(overlay), "state": str(state_path)})
    store.transition(job, "completed")
    return job


def execute_overlay_connect(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    overlay = Path(str(job.parameters.get("overlay", ""))).expanduser().resolve()
    nbd = str(job.parameters.get("nbd_device", ""))
    if (
        not overlay.is_file()
        or overlay.suffix != ".qcow2"
        or store.case.resolve() not in overlay.parents
    ):
        raise RescueError(f"overlay is missing or not QCOW2: {overlay}")
    if not NBD_DEVICE.fullmatch(nbd):
        raise RescueError(f"invalid NBD device: {nbd}")
    require_tool("qemu-nbd")
    require_tool("qemu-img")
    require_block_device(nbd)
    backing = _overlay_backing(overlay)
    store.transition(job, "running", current_step="connect-overlay")
    run(["qemu-nbd", "--connect", nbd, overlay])
    try:
        pid = _nbd_pid(nbd)
        overlay_stat = overlay.stat()
        state_path = _write_state(
            store,
            job,
            {
                "state_version": 2,
                "backing_device": str(backing),
                "overlay": str(overlay),
                "overlay_device": overlay_stat.st_dev,
                "overlay_inode": overlay_stat.st_ino,
                "nbd_device": nbd,
                "nbd_pid": pid,
                "connected": True,
            },
        )
    except (OSError, RescueError):
        run(["qemu-nbd", "--disconnect", nbd], check=False)
        raise
    store.complete_step(job, "connect-overlay", {"state": str(state_path), "nbd_device": nbd})
    store.transition(job, "completed")
    return job


def execute_overlay_disconnect(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    nbd = str(job.parameters.get("nbd_device", ""))
    if not NBD_DEVICE.fullmatch(nbd):
        raise RescueError(f"invalid NBD device: {nbd}")
    require_tool("qemu-nbd")
    require_block_device(nbd)
    store.transition(job, "running", current_step="disconnect-overlay")
    run(["qemu-nbd", "--disconnect", nbd])
    state_path = _write_state(store, job, {"nbd_device": nbd, "connected": False})
    store.complete_step(job, "disconnect-overlay", {"state": str(state_path)})
    store.transition(job, "completed")
    return job


def execute_overlay_cleanup(store: JobStore, job: RecoveryJob) -> RecoveryJob:
    state_path = Path(str(job.parameters.get("state", ""))).expanduser().resolve()
    case_root = store.case.resolve()
    if not state_path.is_file() or case_root not in state_path.parents:
        raise RescueError("overlay cleanup state must be a file inside the recovery case")
    state = json.loads(state_path.read_text())
    store.transition(job, "running", current_step="cleanup-overlay")
    nbd = state.get("nbd_device")
    disconnected = False
    if state.get("connected") and isinstance(nbd, str) and NBD_DEVICE.fullmatch(nbd):
        require_tool("qemu-nbd")
        run(["qemu-nbd", "--disconnect", nbd], check=False)
        disconnected = True
    removed = False
    overlay_value = state.get("overlay")
    if job.parameters.get("remove_overlay") is True and overlay_value:
        overlay = Path(str(overlay_value)).resolve()
        if case_root not in overlay.parents:
            raise RescueError("refuse to remove overlay outside the recovery case")
        overlay.unlink(missing_ok=True)
        removed = True
    state["connected"] = False
    state["cleaned"] = True
    _write_state(store, job, state)
    store.complete_step(job, "cleanup-overlay", {"disconnected": disconnected, "removed": removed})
    store.transition(job, "completed")
    return job
