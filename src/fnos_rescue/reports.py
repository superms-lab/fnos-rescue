from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .jobs import JobStore


def case_report(case: str | Path) -> dict[str, Any]:
    store = JobStore(case)
    jobs = store.list()
    statuses = Counter(job.status for job in jobs)
    kinds = Counter(job.kind for job in jobs)
    completed_steps = sum(len(job.completed_steps) for job in jobs)
    failure_records = 0
    for job in jobs:
        failures = store.root / job.job_id / "failures.jsonl"
        if failures.is_file():
            failure_records += len(failures.read_text().splitlines())
    return {
        "case": str(store.case.resolve()),
        "jobs": len(jobs),
        "statuses": dict(sorted(statuses.items())),
        "kinds": dict(sorted(kinds.items())),
        "completed_steps": completed_steps,
        "failure_records": failure_records,
        "ready": bool(jobs)
        and failure_records == 0
        and set(statuses) == {"completed"},
    }
