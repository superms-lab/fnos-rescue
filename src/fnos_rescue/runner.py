from __future__ import annotations

import shutil
import subprocess
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .errors import RescueError, ToolMissingError
from .errors import JobControlRequested


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
    env: dict[str, str] | None = None,
) -> CommandResult:
    args = tuple(str(value) for value in argv)
    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=text,
        timeout=timeout,
        env={**os.environ, **env} if env else None,
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


def run_interruptible(
    argv: Iterable[str | Path],
    *,
    control: Callable[[], str | None],
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    poll_interval: float = 0.2,
) -> CommandResult:
    args = tuple(str(value) for value in argv)
    started = time.monotonic()
    process = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, **env} if env else None,
    )
    while process.poll() is None:
        action = control()
        if action in {"pause", "cancel"}:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.communicate()
            raise JobControlRequested(action)
        if timeout is not None and time.monotonic() - started > timeout:
            process.kill()
            stdout, stderr = process.communicate()
            raise RescueError(f"{args[0]} timed out after {timeout}s: {stderr.strip() or stdout.strip()}")
        time.sleep(poll_interval)
    stdout, stderr = process.communicate()
    result = CommandResult(args, process.returncode, stdout, stderr)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RescueError(f"{args[0]} exited {result.returncode}: {message}")
    return result
