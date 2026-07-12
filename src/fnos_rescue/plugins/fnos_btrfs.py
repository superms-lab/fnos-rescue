from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fnos_rescue.devices import require_block_device
from fnos_rescue.runner import require_tool, run
from fnos_rescue.safety import assert_read_only

from .base import FilesystemPlugin


KEY_VALUE = re.compile(r"^([a-zA-Z0-9_.]+)\s+(.+?)\s*$")


def parse_dump_super(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = KEY_VALUE.match(line)
        if not match:
            continue
        key, value = match.groups()
        parsed[key] = value
    parsed["valid_magic"] = "_BHRfS_M [match]" in text
    parsed["valid_checksum"] = "[match]" in parsed.get("csum", "")
    return parsed


class FnosBtrfsPlugin(FilesystemPlugin):
    name = "fnos-btrfs"

    def probe(self, device: Path) -> dict[str, Any]:
        block = require_block_device(device)
        assert_read_only(block)
        require_tool("btrfs")
        mirrors = []
        for mirror in range(3):
            result = run(
                ["btrfs", "inspect-internal", "dump-super", "-f", "-s", str(mirror), block],
                check=False,
            )
            evidence = parse_dump_super(result.stdout + "\n" + result.stderr)
            evidence["mirror"] = mirror
            evidence["returncode"] = result.returncode
            mirrors.append(evidence)
        return {"plugin": self.name, "device": str(block), "mirrors": mirrors}
