import json
import tempfile
import unittest
import stat
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fnos_rescue.cases import RecoveryCase, assert_case_source
from fnos_rescue.devices import DeviceFacts
from fnos_rescue.errors import SafetyError


class RecoveryCaseTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        facts = DeviceFacts(
            path="/dev/test",
            name="test",
            size_bytes=4_000_000_000,
            read_only=True,
            device_type="disk",
            filesystem=None,
            model="Fixture",
            serial="SAFE-SERIAL",
            uuid=None,
            mountpoints=(),
        )
        case = RecoveryCase.create(facts, filesystem="btrfs")
        with tempfile.TemporaryDirectory() as temporary:
            path = case.save(Path(temporary) / "case")
            loaded = RecoveryCase.load(path)
            self.assertEqual(loaded.case_id, case.case_id)
            self.assertEqual(loaded.source["serial"], "SAFE-SERIAL")
            self.assertEqual(loaded.filesystem, "btrfs")
            self.assertEqual(json.loads(path.read_text())["schema_version"], 1)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_runtime_source_identity_is_rechecked(self) -> None:
        facts = DeviceFacts(
            path="/dev/test", name="test", size_bytes=1000, read_only=True,
            device_type="disk", filesystem="btrfs", model="Fixture",
            serial="SERIAL", uuid=None, mountpoints=(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            case = RecoveryCase.create(facts)
            case_path = Path(temporary) / case.case_id
            case.save(case_path)
            with patch("fnos_rescue.devices.inspect_device", return_value=facts), patch(
                "fnos_rescue.devices.block_identity", return_value="8:1"
            ), patch(
                "fnos_rescue.devices.related_block_identities", return_value={"8:0", "8:1"}
            ), patch(
                "fnos_rescue.safety.assert_source_graph_read_only"
            ):
                self.assertEqual(assert_case_source(case_path, "/dev/test").serial, "SERIAL")
            with patch("fnos_rescue.devices.inspect_device", return_value=replace(facts, serial="OTHER")), patch(
                "fnos_rescue.devices.block_identity", return_value="8:1"
            ), patch(
                "fnos_rescue.devices.related_block_identities", return_value={"8:0", "8:1"}
            ), patch(
                "fnos_rescue.safety.assert_source_graph_read_only"
            ):
                with self.assertRaises(SafetyError):
                    assert_case_source(case_path, "/dev/test")


if __name__ == "__main__":
    unittest.main()
