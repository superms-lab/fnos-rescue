from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .errors import RescueError, ToolMissingError


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ToolMissingError(f"required tool is not installed: {name}")
    return path


def run(
    argv: Iterable[str | Path],
    *,
    check: bool = True,
    timeout: float | None = None,
    text: bool = True,
) -> CommandResult:
    args = tuple(str(value) for value in argv)
    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=text,
        timeout=timeout,
    )
    result = CommandResult(
        argv=args,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if check and result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RescueError(f"{args[0]} exited {result.returncode}: {message}")
    return result
