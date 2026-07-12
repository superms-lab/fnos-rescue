import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


class FnosPackagingTests(unittest.TestCase):
    def test_web_service_is_loopback_only_and_sandboxed(self) -> None:
        service = Path("packaging/fnos/fnos-rescue-web.service").read_text()
        self.assertIn("--host 127.0.0.1", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ReadWritePaths=/var/lib/fnos-rescue", service)
        installer = Path("packaging/fnos/install.sh").read_text()
        self.assertIn("systemctl is-active --quiet", installer)
        self.assertIn("install -d -m 0700 /var/lib/fnos-rescue", installer)

    def test_builds_native_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tools = Path(temporary)
            for name in ("scan_btrfs_roots", "fnos-rescue-btrfs"):
                (tools / name).write_text("#!/bin/sh\nexit 0\n")
                (tools / name).chmod(0o755)
            env = {**os.environ, "FNOS_RESCUE_TOOLS_DIR": str(tools)}
            result = subprocess.run(["bash", "scripts/build-fnos-package.sh"], check=True, text=True, capture_output=True, env=env)
            archive = Path(result.stdout.strip())
            self.assertTrue(archive.is_file())
            with tarfile.open(archive) as bundle:
                names = bundle.getnames()
                manifest_name = next(name for name in names if name.endswith("/manifest.json"))
                manifest = json.load(bundle.extractfile(manifest_name))
                self.assertTrue(any(name.endswith("/app/bin/scan_btrfs_roots") for name in names))
                self.assertTrue(any(name.endswith("/app/bin/fnos-rescue-btrfs") for name in names))
                self.assertTrue(any(name.endswith("/fnos-rescue-web.service") for name in names))
                self.assertFalse(any("/__pycache__/" in name for name in names))
            self.assertEqual(manifest["name"], "FNOS Rescue")
            self.assertEqual(manifest["os"], "fnOS")


if __name__ == "__main__":
    unittest.main()
