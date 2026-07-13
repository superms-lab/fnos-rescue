from __future__ import annotations

import shutil
import subprocess
import os
import signal
import tempfile
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
    stdout_path: str | Path | None = None,
    stderr_path: str | Path | None = None,
    append: bool = True,
) -> CommandResult:
    if stdout_path is not None and stderr_path is not None:
        return run_streaming(
            argv,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            control=control,
            timeout=timeout,
            env=env,
            poll_interval=poll_interval,
            append=append,
        )
    with tempfile.TemporaryDirectory(prefix="fnos-rescue-command-") as temporary:
        return run_streaming(
            argv,
            stdout_path=Path(temporary) / "stdout.log",
            stderr_path=Path(temporary) / "stderr.log",
            control=control,
            timeout=timeout,
            env=env,
            poll_interval=poll_interval,
            append=False,
        )


def _tail(path: Path, start: int, limit: int = 1 << 20) -> str:
    with path.open("rb") as handle:
        end = handle.seek(0, os.SEEK_END)
        handle.seek(max(start, end - limit))
        return handle.read().decode("utf-8", errors="replace")


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.wait()


def run_streaming(
    argv: Iterable[str | Path],
    *,
    stdout_path: str | Path,
    stderr_path: str | Path,
    control: Callable[[], str | None] | None = None,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    poll_interval: float = 0.2,
    append: bool = False,
) -> CommandResult:
    """Run with child output continuously drained to bounded-per-job disk logs."""
    args = tuple(str(value) for value in argv)
    started = time.monotonic()
    stdout_target = Path(stdout_path)
    stderr_target = Path(stderr_path)
    stdout_target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    stderr_target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = "ab" if append else "wb"
    with stdout_target.open(mode, buffering=0) as stdout_handle, stderr_target.open(mode, buffering=0) as stderr_handle:
        stdout_start = stdout_handle.tell()
        stderr_start = stderr_handle.tell()
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env={**os.environ, **env} if env else None,
            start_new_session=True,
        )
        while process.poll() is None:
            action = control() if control else None
            if action in {"pause", "cancel"}:
                _stop_process(process)
                os.fsync(stdout_handle.fileno())
                os.fsync(stderr_handle.fileno())
                raise JobControlRequested(action)
            if timeout is not None and time.monotonic() - started > timeout:
                _stop_process(process)
                os.fsync(stdout_handle.fileno())
                os.fsync(stderr_handle.fileno())
                stderr = _tail(stderr_target, stderr_start)
                stdout = _tail(stdout_target, stdout_start)
                raise RescueError(f"{args[0]} timed out after {timeout}s: {stderr.strip() or stdout.strip()}")
            time.sleep(poll_interval)
        os.fsync(stdout_handle.fileno())
        os.fsync(stderr_handle.fileno())
    stdout = _tail(stdout_target, stdout_start)
    stderr = _tail(stderr_target, stderr_start)
    result = CommandResult(args, process.returncode, stdout, stderr)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RescueError(f"{args[0]} exited {result.returncode}: {message}")
    return result
