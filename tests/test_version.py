import tomllib
import unittest
from pathlib import Path

import fnos_rescue


class VersionTests(unittest.TestCase):
    def test_pyproject_and_runtime_versions_match(self) -> None:
        document = tomllib.loads(Path("pyproject.toml").read_text())
        self.assertEqual(document["project"]["version"], fnos_rescue.__version__)


if __name__ == "__main__":
    unittest.main()
