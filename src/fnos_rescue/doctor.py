from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from typing import Any


CORE_TOOLS = ("lsblk", "blockdev", "findmnt", "file")
RECOVERY_TOOLS = ("btrfs", "mdadm", "qemu-img", "qemu-nbd", "dumpe2fs", "ntfsinfo")


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    platform: str
    python: str
    core_tools: dict[str, str | None]
    recovery_tools: dict[str, str | None]
    problems: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tools(names: tuple[str, ...]) -> dict[str, str | None]:
    return {name: shutil.which(name) for name in names}


def diagnose() -> DoctorReport:
    system = platform.system()
    core = _tools(CORE_TOOLS)
    recovery = _tools(RECOVERY_TOOLS)
    problems: list[str] = []
    if system != "Linux":
        problems.append("raw-device recovery requires Linux")
    if sys.version_info < (3, 11):
        problems.append("Python 3.11 or newer is required")
    missing_core = [name for name, path in core.items() if not path]
    if missing_core:
        problems.append(f"missing core tools: {', '.join(missing_core)}")
    missing_recovery = [name for name, path in recovery.items() if not path]
    if missing_recovery:
        problems.append(f"missing recovery tools: {', '.join(missing_recovery)}")
    return DoctorReport(
        ok=not problems,
        platform=system,
        python=platform.python_version(),
        core_tools=core,
        recovery_tools=recovery,
        problems=tuple(problems),
    )
