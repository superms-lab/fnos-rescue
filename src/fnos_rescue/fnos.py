from __future__ import annotations

import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import RescueError
from .runner import run


FNOS_MARKERS = (Path("/fs"), Path("/var/apps"), Path("/usr/local/apps"))
QUIESCE_SERVICES = (
    "mediasrv.service",
    "multiple-downloads.service",
    "trim_file_monitor.service",
    "smbd.service",
    "nfs-server.service",
)


@dataclass(frozen=True)
class FnosEnvironment:
    detected: bool
    architecture: str
    app_root: str | None
    markers: tuple[str, ...]
    active_services: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_fnos() -> FnosEnvironment:
    markers = tuple(str(path) for path in FNOS_MARKERS if path.exists())
    detected = Path("/fs").exists() and len(markers) >= 2
    app_root = "/var/apps/fnos-rescue" if Path("/var/apps").is_dir() else None
    active: list[str] = []
    if detected:
        for service in QUIESCE_SERVICES:
            result = run(["systemctl", "is-active", service], check=False)
            if result.stdout.strip() == "active":
                active.append(service)
    return FnosEnvironment(detected, platform.machine(), app_root, markers, tuple(active))


def quiesce_plan(source_device: str) -> dict[str, Any]:
    environment = detect_fnos()
    if not environment.detected:
        raise RescueError("fnOS environment was not detected")
    result = run(
        ["lsblk", "--noheadings", "--output", "PATH,MOUNTPOINTS", source_device],
        check=False,
    )
    mounted = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {
        "source_device": source_device,
        "mounted_layers": mounted,
        "services_to_stop": list(environment.active_services),
        "actions": [
            "record currently active services",
            "stop only services using the selected source",
            "unmount selected source layers",
            "set selected device tree read-only",
            "run recovery",
            "restore only services stopped by this case",
        ],
        "dry_run": True,
    }
