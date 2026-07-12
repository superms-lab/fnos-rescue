import unittest
from pathlib import Path
from unittest.mock import patch

from fnos_rescue.plugins.ext4 import Ext4DiagnosticPlugin
from fnos_rescue.plugins.ntfs import NtfsDiagnosticPlugin
from fnos_rescue.runner import CommandResult


class DiagnosticPluginTests(unittest.TestCase):
    def test_ext4_parses_header_without_writing(self) -> None:
        result = CommandResult(("dumpe2fs",), 0, "Filesystem UUID: abc\nBlock size: 4096\n", "")
        with patch("fnos_rescue.plugins.ext4.require_block_device", return_value=Path("/dev/test")), patch(
            "fnos_rescue.plugins.ext4.assert_read_only"
        ), patch("fnos_rescue.plugins.ext4.require_tool"), patch(
            "fnos_rescue.plugins.ext4.run", return_value=result
        ):
            evidence = Ext4DiagnosticPlugin().probe(Path("/dev/test"))
        self.assertEqual(evidence["fields"]["Block size"], "4096")
        self.assertTrue(evidence["read_only"])

    def test_ntfs_uses_ntfsinfo_read_only_diagnostic(self) -> None:
        result = CommandResult(("ntfsinfo",), 0, "Volume Information\n", "")
        with patch("fnos_rescue.plugins.ntfs.require_block_device", return_value=Path("/dev/test")), patch(
            "fnos_rescue.plugins.ntfs.assert_read_only"
        ), patch("fnos_rescue.plugins.ntfs.require_tool"), patch(
            "fnos_rescue.plugins.ntfs.run", return_value=result
        ):
            evidence = NtfsDiagnosticPlugin().probe(Path("/dev/test"))
        self.assertEqual(evidence["returncode"], 0)
        self.assertTrue(evidence["read_only"])


if __name__ == "__main__":
    unittest.main()
