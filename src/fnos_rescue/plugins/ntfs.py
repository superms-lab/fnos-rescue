from __future__ import annotations

from pathlib import Path
from typing import Any

from ..devices import require_block_device
from ..runner import require_tool, run
from ..safety import assert_read_only
from .base import FilesystemPlugin


class NtfsDiagnosticPlugin(FilesystemPlugin):
    name = "ntfs-diagnostic"

    def probe(self, device: Path) -> dict[str, Any]:
        block = require_block_device(device)
        assert_read_only(block)
        require_tool("ntfsinfo")
        result = run(["ntfsinfo", "--mft", block], check=False)
        return {
            "plugin": self.name,
            "device": str(block),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "read_only": True,
        }
