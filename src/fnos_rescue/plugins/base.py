from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class FilesystemPlugin(ABC):
    name: str

    @abstractmethod
    def probe(self, device: Path) -> dict[str, Any]:
        """Return read-only filesystem evidence."""
