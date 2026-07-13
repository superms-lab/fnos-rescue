import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fnos_rescue.devices import DeviceFacts, iter_device_paths, related_block_devices, require_block_device
from fnos_rescue.errors import SafetyError
from fnos_rescue.safety import assert_destination_not_source, confirm_serial


def fixture() -> DeviceFacts:
    partition = DeviceFacts(
        path="/dev/test1",
        name="test1",
        size_bytes=900,
        read_only=True,
        device_type="part",
        filesystem="linux_raid_member",
        model=None,
        serial=None,
        uuid="array",
        mountpoints=(),
    )
    return DeviceFacts(
        path="/dev/test",
        name="test",
        size_bytes=1000,
        read_only=True,
        device_type="disk",
        filesystem=None,
        model="Fixture",
        serial="SERIAL-123",
        uuid=None,
        mountpoints=(),
        children=(partition,),
    )


class SafetyTests(unittest.TestCase):
    @patch("fnos_rescue.devices.platform.system", return_value="Linux")
    def test_block_device_path_must_resolve_inside_dev(self, _system) -> None:
        with self.assertRaises(SafetyError):
            require_block_device("/tmp/not-a-device")

    def test_requires_exact_serial(self) -> None:
        self.assertEqual(confirm_serial(fixture(), "SERIAL-123"), "SERIAL-123")
        with self.assertRaises(SafetyError):
            confirm_serial(fixture(), "SERIAL-124")

    def test_children_are_protected_before_parent(self) -> None:
        self.assertEqual(list(iter_device_paths(fixture())), ["/dev/test1", "/dev/test"])

    def test_kernel_graph_includes_partitions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = root / "devices" / "block" / "sda"
            partition = node / "sda1"
            partition.mkdir(parents=True)
            (node / "dev").write_text("8:0\n")
            (node / "holders").mkdir()
            (node / "slaves").mkdir()
            (partition / "dev").write_text("8:1\n")
            (partition / "partition").write_text("1\n")
            (partition / "holders").mkdir()
            (partition / "slaves").mkdir()
            sys_dev = root / "sys-dev-block"
            sys_dev.mkdir()
            (sys_dev / "8:0").symlink_to(node)
            dev_root = root / "dev"
            dev_root.mkdir()
            (dev_root / "sda").touch()
            (dev_root / "sda1").touch()
            with patch("fnos_rescue.devices.block_identity", return_value="8:0"):
                paths = related_block_devices("/dev/source", sys_dev_block=sys_dev, dev_root=dev_root)
            self.assertEqual(paths, sorted([str((dev_root / "sda").resolve()), str((dev_root / "sda1").resolve())]))

    def test_destination_comparison_uses_kernel_identities_not_path_names(self) -> None:
        with patch("fnos_rescue.safety.destination_source", return_value="/dev/dm-0"), patch(
            "fnos_rescue.safety.related_block_identities", side_effect=[{"8:0", "8:1"}, {"253:0", "8:1"}]
        ):
            with self.assertRaises(SafetyError):
                assert_destination_not_source("/dev/disk/by-id/source", "/mnt/output")

    def test_unknown_non_block_destination_fails_closed(self) -> None:
        result = type("Result", (), {"stdout": "zfs\n"})()
        with patch("fnos_rescue.safety.destination_source", return_value="pool/recovery"), patch(
            "fnos_rescue.safety.run", return_value=result
        ):
            with self.assertRaises(SafetyError):
                assert_destination_not_source("/dev/sda", "/recovery")


if __name__ == "__main__":
    unittest.main()
