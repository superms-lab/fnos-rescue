from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .devices import DeviceFacts
from .errors import SafetyError


SCHEMA_VERSION = 1


@dataclass
class RecoveryCase:
    case_id: str
    created_at: str
    source: dict[str, Any]
    filesystem: str | None = None
    status: str = "created"
    artifacts: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(cls, source: DeviceFacts, filesystem: str | None = None) -> "RecoveryCase":
        return cls(
            case_id=f"case-{uuid.uuid4().hex[:12]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            source=source.to_dict(),
            filesystem=filesystem or source.filesystem,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, directory: str | Path) -> Path:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=False, mode=0o700)
        for name in (
            "superblocks",
            "scans",
            "mappings",
            "inventories",
            "validation",
            "logs",
            "jobs",
        ):
            (root / name).mkdir(mode=0o700)
        target = root / "case.json"
        with target.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        target.chmod(0o600)
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return target

    @classmethod
    def load(cls, path: str | Path) -> "RecoveryCase":
        source = Path(path)
        if source.is_dir():
            source = source / "case.json"
        return cls(**json.loads(source.read_text()))


def assert_case_source(case_path: str | Path, supplied: str | Path) -> DeviceFacts:
    """Re-identify and lock the current device before every source-bound job."""
    from .devices import block_identity, find_serial, inspect_device, related_block_identities
    from .safety import assert_source_graph_read_only

    case = RecoveryCase.load(case_path)
    recorded_path = str(case.source.get("path") or "")
    value = str(supplied)
    if not recorded_path.startswith("/dev/") or not value.startswith("/dev/"):
        raise SafetyError("recovery case has no valid source device")
    current = inspect_device(recorded_path)
    recorded_serial = str(case.source.get("serial") or "")
    if not recorded_serial or find_serial(current) != recorded_serial:
        raise SafetyError("source serial no longer matches the recovery case")
    if int(case.source.get("size_bytes") or 0) != current.size_bytes:
        raise SafetyError("source capacity no longer matches the recovery case")
    assert_source_graph_read_only(recorded_path)
    assert_source_graph_read_only(value)
    if block_identity(value) not in related_block_identities(recorded_path):
        raise SafetyError("job source device is not a layer of the recovery case source")
    return current
