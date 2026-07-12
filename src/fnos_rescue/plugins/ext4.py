from __future__ import annotations

from pathlib import Path
from typing import Any

from ..devices import require_block_device
from ..runner import require_tool, run
from ..safety import assert_read_only
from .base import FilesystemPlugin


class Ext4DiagnosticPlugin(FilesystemPlugin):
    name = "ext4-diagnostic"

    def probe(self, device: Path) -> dict[str, Any]:
        block = require_block_device(device)
        assert_read_only(block)
        require_tool("dumpe2fs")
        result = run(["dumpe2fs", "-h", block], check=False)
        fields: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        return {
            "plugin": self.name,
            "device": str(block),
            "returncode": result.returncode,
            "fields": fields,
            "stderr": result.stderr.strip(),
            "read_only": True,
        }
