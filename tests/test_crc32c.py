import importlib.util
import unittest
from pathlib import Path


def load_helper():
    path = Path("helpers/crc32c_compat.py")
    spec = importlib.util.spec_from_file_location("crc32c_compat", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class CRC32CTests(unittest.TestCase):
    def test_standard_check_value(self) -> None:
        helper = load_helper()
        self.assertEqual(helper.crc32c(b"123456789"), 0xE3069283)


if __name__ == "__main__":
    unittest.main()
