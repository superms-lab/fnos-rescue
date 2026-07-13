import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


HELPERS = Path("helpers").resolve()


def load(name: str):
    sys.path.insert(0, str(HELPERS))
    try:
        spec = importlib.util.spec_from_file_location(name, HELPERS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(HELPERS))


class OverlayWriteGuardTests(unittest.TestCase):
    def test_historical_root_never_opens_raw_device_when_overlay_proof_fails(self):
        module = load("set_btrfs_historical_root")
        argv = ["helper", "/dev/sda", "4096", "1", "--overlay-state", "/tmp/state"]
        with patch.object(sys, "argv", argv), patch.object(
            module, "require_connected_case_overlay", side_effect=RuntimeError("not overlay")
        ), patch.object(module.os, "open") as opened:
            with self.assertRaisesRegex(RuntimeError, "not overlay"):
                module.main()
        opened.assert_not_called()

    def test_synthetic_tree_never_reads_cache_or_opens_device_when_proof_fails(self):
        module = load("build_synthetic_chunk_tree")
        argv = [
            "helper", "/dev/sda", "/tmp/cache", "--generation", "1",
            "--tree-root", "4096", "--tree-root-level", "0", "--chunk-root", "8192",
            "--system-logical", "0", "--system-physical", "0",
            "--chunk-uuid", "11111111-2222-3333-4444-555555555555",
            "--confirm-overlay", "--overlay-state", "/tmp/state",
        ]
        with patch.object(sys, "argv", argv), patch.object(
            module, "require_connected_case_overlay", side_effect=RuntimeError("not overlay")
        ), patch.object(module, "read_cache") as read_cache, patch.object(module.os, "open") as opened:
            with self.assertRaisesRegex(RuntimeError, "not overlay"):
                module.main()
        read_cache.assert_not_called()
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
