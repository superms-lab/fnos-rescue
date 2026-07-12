import unittest

from fnos_rescue.destinations import (
    DestinationFacts,
    assert_destination_ready,
    classify_filesystem,
    parse_findmnt,
)
from fnos_rescue.errors import SafetyError


class DestinationTests(unittest.TestCase):
    def test_classifies_local_smb_and_nfs(self) -> None:
        self.assertEqual(classify_filesystem("ext4"), "local")
        self.assertEqual(classify_filesystem("cifs"), "smb")
        self.assertEqual(classify_filesystem("nfs4"), "nfs")

    def test_parses_findmnt_document(self) -> None:
        parsed = parse_findmnt({"filesystems": [{
            "source": "server:/export", "target": "/mnt/out", "fstype": "nfs4",
            "options": "rw,nosuid,nodev"
        }]})
        self.assertEqual(parsed, ("server:/export", "/mnt/out", "nfs4", ("rw", "nosuid", "nodev")))

    def facts(self, **changes):
        values = dict(
            path="/mnt/out", existing_ancestor="/mnt/out", source="/dev/sdb1",
            mountpoint="/mnt/out", filesystem="ext4", kind="local", read_only=False,
            writable=True, free_bytes=1000, total_bytes=2000,
        )
        values.update(changes)
        return DestinationFacts(**values)

    def test_rejects_read_only_and_insufficient_targets(self) -> None:
        assert_destination_ready(self.facts(), 900)
        with self.assertRaises(SafetyError):
            assert_destination_ready(self.facts(read_only=True), 1)
        with self.assertRaises(SafetyError):
            assert_destination_ready(self.facts(free_bytes=10), 11)


if __name__ == "__main__":
    unittest.main()
