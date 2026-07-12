import json
import subprocess
import tarfile
import unittest
from pathlib import Path


class FnosPackagingTests(unittest.TestCase):
    def test_builds_native_archive(self) -> None:
        result = subprocess.run(["bash", "scripts/build-fnos-package.sh"], check=True, text=True, capture_output=True)
        archive = Path(result.stdout.strip())
        self.assertTrue(archive.is_file())
        with tarfile.open(archive) as bundle:
            manifest_name = next(name for name in bundle.getnames() if name.endswith("/manifest.json"))
            manifest = json.load(bundle.extractfile(manifest_name))
        self.assertEqual(manifest["name"], "FNOS Rescue")
        self.assertEqual(manifest["os"], "fnOS")


if __name__ == "__main__":
    unittest.main()
