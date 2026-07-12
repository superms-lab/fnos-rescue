from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .devices import DeviceFacts


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
        root.mkdir(parents=True, exist_ok=False)
        for name in ("superblocks", "scans", "mappings", "inventories", "validation", "logs"):
            (root / name).mkdir()
        target = root / "case.json"
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "RecoveryCase":
        source = Path(path)
        if source.is_dir():
            source = source / "case.json"
        return cls(**json.loads(source.read_text()))
