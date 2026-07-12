import unittest

from fnos_rescue.devices import DeviceFacts, iter_device_paths
from fnos_rescue.errors import SafetyError
from fnos_rescue.safety import confirm_serial


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
    def test_requires_exact_serial(self) -> None:
        self.assertEqual(confirm_serial(fixture(), "SERIAL-123"), "SERIAL-123")
        with self.assertRaises(SafetyError):
            confirm_serial(fixture(), "SERIAL-124")

    def test_children_are_protected_before_parent(self) -> None:
        self.assertEqual(list(iter_device_paths(fixture())), ["/dev/test1", "/dev/test"])


if __name__ == "__main__":
    unittest.main()
