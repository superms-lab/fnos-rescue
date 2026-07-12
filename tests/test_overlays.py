import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fnos_rescue.jobs import JobStore
from fnos_rescue.overlays import (
    execute_overlay_cleanup,
    execute_overlay_connect,
    execute_overlay_create,
    execute_overlay_disconnect,
)
from fnos_rescue.runner import CommandResult


class OverlayTests(unittest.TestCase):
    def make_store(self, root: Path) -> JobStore:
        case = root / "case"
        case.mkdir()
        (case / "case.json").write_text("{}\n")
        return JobStore(case)

    def test_create_overlay_isolated_in_job_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self.make_store(Path(temporary))
            job = store.create("overlay-create", {"backing_device": "/dev/test"})
            def fake_run(argv, **_kwargs):
                Path(argv[-1]).write_bytes(b"qcow2")
                return CommandResult(tuple(map(str, argv)), 0, "", "")
            with patch("fnos_rescue.overlays.require_block_device", return_value=Path("/dev/test")), patch(
                "fnos_rescue.overlays.assert_read_only"
            ), patch("fnos_rescue.overlays.require_tool"), patch(
                "fnos_rescue.overlays.run", side_effect=fake_run
            ):
                completed = execute_overlay_create(store, job)
            self.assertEqual(completed.status, "completed")
            self.assertTrue((store.root / job.job_id / "recovery-overlay.qcow2").is_file())

    def test_connect_and_disconnect_validate_nbd_device(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.make_store(root)
            overlay = root / "test.qcow2"
            overlay.write_bytes(b"qcow2")
            connect = store.create("overlay-connect", {"overlay": str(overlay), "nbd_device": "/dev/nbd7"})
            disconnect = store.create("overlay-disconnect", {"nbd_device": "/dev/nbd7"})
            result = CommandResult(("qemu-nbd",), 0, "", "")
            with patch("fnos_rescue.overlays.require_block_device", return_value=Path("/dev/nbd7")), patch(
                "fnos_rescue.overlays.require_tool"
            ), patch("fnos_rescue.overlays.run", return_value=result):
                self.assertEqual(execute_overlay_connect(store, connect).status, "completed")
                self.assertEqual(execute_overlay_disconnect(store, disconnect).status, "completed")
            bad = store.create("overlay-connect", {"overlay": str(overlay), "nbd_device": "/dev/sda"})
            with self.assertRaises(Exception):
                execute_overlay_connect(store, bad)

    def test_cleanup_only_removes_case_owned_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.make_store(root)
            owner = store.create("overlay-create", {})
            directory = store.root / owner.job_id
            overlay = directory / "recovery-overlay.qcow2"
            overlay.write_bytes(b"qcow2")
            state = directory / "overlay-state.json"
            state.write_text('{"overlay":"%s","nbd_device":null,"connected":false}\n' % overlay)
            cleanup = store.create("overlay-cleanup", {"state": str(state), "remove_overlay": True})
            completed = execute_overlay_cleanup(store, cleanup)
            self.assertEqual(completed.status, "completed")
            self.assertFalse(overlay.exists())


if __name__ == "__main__":
    unittest.main()
