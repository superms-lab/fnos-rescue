import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import importlib.util


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/generate-release-metadata.py"
SPEC = importlib.util.spec_from_file_location("release_metadata", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReleaseMetadataTests(unittest.TestCase):
    def test_sbom_components_are_pinned(self):
        components = MODULE.components()
        self.assertTrue(components)
        self.assertTrue(all(item["version"] != "latest" for item in components))
        self.assertTrue(any(item["name"] == "react" for item in components))

    def test_checksum_is_sha256(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact"
            path.write_bytes(b"fnos-rescue")
            self.assertEqual(len(MODULE.sha256(path)), 64)


if __name__ == "__main__":
    unittest.main()
