import json
import tempfile
import unittest
import stat
from pathlib import Path

from fnos_rescue.cases import RecoveryCase
from fnos_rescue.devices import DeviceFacts


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


if __name__ == "__main__":
    unittest.main()
