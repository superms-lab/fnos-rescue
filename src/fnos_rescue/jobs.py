from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .errors import RescueError


JOB_SCHEMA_VERSION = 1
TERMINAL_STATES = {"completed", "cancelled"}
JOB_ID = re.compile(r"^job-[0-9a-f]{12}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durable_text(path: Path, value: str, mode: str = "w") -> None:
    with path.open(mode, encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


@dataclass
class RecoveryJob:
    job_id: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    parameters: dict[str, Any]
    completed_steps: list[str]
    current_step: str | None = None
    error: str | None = None
    schema_version: int = JOB_SCHEMA_VERSION

    @classmethod
    def create(cls, kind: str, parameters: dict[str, Any]) -> "RecoveryJob":
        timestamp = _now()
        return cls(
            job_id=f"job-{uuid.uuid4().hex[:12]}",
            kind=kind,
            status="queued",
            created_at=timestamp,
            updated_at=timestamp,
            parameters=parameters,
            completed_steps=[],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobStore:
    def __init__(self, case: str | Path):
        self.case = Path(case)
        if self.case.is_file():
            self.case = self.case.parent
        if not (self.case / "case.json").is_file():
            raise RescueError(f"not a recovery case directory: {self.case}")
        self.root = self.case / "jobs"
        self.root.mkdir(exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def create(self, kind: str, parameters: dict[str, Any]) -> RecoveryJob:
        job = RecoveryJob.create(kind, parameters)
        directory = self.root / job.job_id
        directory.mkdir(mode=0o700)
        _fsync_directory(self.root)
        self._write(job)
        self.append_event(job, "job.created", {"kind": kind})
        return job

    def load(self, job_id: str) -> RecoveryJob:
        if not JOB_ID.fullmatch(job_id):
            raise RescueError(f"invalid job id: {job_id}")
        path = self.root / job_id / "job.json"
        if not path.is_file():
            raise RescueError(f"job does not exist: {job_id}")
        return RecoveryJob(**json.loads(path.read_text()))

    def list(self) -> list[RecoveryJob]:
        return [self.load(path.name) for path in sorted(self.root.glob("job-*")) if path.is_dir()]

    def transition(
        self,
        job: RecoveryJob,
        status: str,
        *,
        current_step: str | None = None,
        error: str | None = None,
    ) -> RecoveryJob:
        if job.status in TERMINAL_STATES and status != job.status:
            raise RescueError(f"cannot transition terminal job {job.job_id} from {job.status}")
        job.status = status
        job.current_step = current_step
        job.error = error
        job.updated_at = _now()
        self._write(job)
        self.append_event(job, f"job.{status}", {"step": current_step, "error": error})
        return job

    def complete_step(self, job: RecoveryJob, step: str, details: dict[str, Any] | None = None) -> None:
        if step not in job.completed_steps:
            job.completed_steps.append(step)
        job.current_step = None
        job.updated_at = _now()
        self._write(job)
        self.append_event(job, "step.completed", {"step": step, **(details or {})})

    def pending_steps(self, job: RecoveryJob, steps: Iterable[str]) -> list[str]:
        return [step for step in steps if step not in job.completed_steps]

    def request_control(self, job: RecoveryJob, action: str) -> None:
        if not JOB_ID.fullmatch(job.job_id):
            raise RescueError(f"invalid job id: {job.job_id}")
        if action not in {"pause", "cancel", "resume"}:
            raise RescueError(f"unsupported job control action: {action}")
        target = self.root / job.job_id / "control.json"
        if action == "resume":
            existed = target.exists()
            target.unlink(missing_ok=True)
            if existed:
                _fsync_directory(target.parent)
            if job.status == "paused":
                self.transition(job, "queued")
        else:
            _durable_text(target, json.dumps({"action": action, "requested_at": _now()}) + "\n")
            _fsync_directory(target.parent)
            self.append_event(job, f"control.{action}", {})

    def requested_action(self, job: RecoveryJob) -> str | None:
        target = self.root / job.job_id / "control.json"
        if not target.is_file():
            return None
        return str(json.loads(target.read_text()).get("action") or "") or None

    def record_failure(self, job: RecoveryJob, item: str, error: str) -> None:
        target = self.root / job.job_id / "failures.jsonl"
        created = not target.exists()
        payload = {"timestamp": _now(), "item": item, "error": error}
        _durable_text(target, json.dumps(payload, ensure_ascii=False) + "\n", mode="a")
        if created:
            _fsync_directory(target.parent)
        self.append_event(job, "item.failed", payload)

    def failure_count(self, job: RecoveryJob) -> int:
        target = self.root / job.job_id / "failures.jsonl"
        if not target.is_file():
            return 0
        with target.open(encoding="utf-8", errors="replace") as handle:
            return sum(1 for line in handle if line.strip())

    def has_failures(self, job: RecoveryJob) -> bool:
        return self.failure_count(job) > 0

    def append_event(self, job: RecoveryJob, event: str, data: dict[str, Any]) -> None:
        target = self.root / job.job_id / "progress.jsonl"
        created = not target.exists()
        payload = {"timestamp": _now(), "job_id": job.job_id, "event": event, "data": data}
        _durable_text(target, json.dumps(payload, ensure_ascii=False) + "\n", mode="a")
        if created:
            _fsync_directory(target.parent)

    def _write(self, job: RecoveryJob) -> None:
        target = self.root / job.job_id / "job.json"
        temporary = target.with_suffix(".json.tmp")
        _durable_text(temporary, json.dumps(job.to_dict(), ensure_ascii=False, indent=2) + "\n")
        temporary.replace(target)
        _fsync_directory(target.parent)
