import json
import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fnos_rescue.destinations import DestinationFacts
from fnos_rescue.executors import _job_lock, execute_job, start_background
from fnos_rescue.jobs import JobStore


class VerifyExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        source_guard = patch("fnos_rescue.executors.assert_case_source")
        source_guard.start()
        self.addCleanup(source_guard.stop)

    def make_store(self, root: Path) -> JobStore:
        case = root / "case"
        case.mkdir()
        (case / "case.json").write_text("{}\n")
        return JobStore(case)

    def ready_destination(self, path: Path) -> DestinationFacts:
        return DestinationFacts(
            path=str(path), existing_ancestor=str(path.parent), source="/dev/test",
            mountpoint=str(path.parent), filesystem="ext4", kind="local", read_only=False,
            writable=True, free_bytes=1_000_000, total_bytes=2_000_000,
        )

    def test_verify_job_writes_results_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "recovered"
            source.mkdir()
            (source / "one.txt").write_text("one")
            (source / "two.txt").write_text("two")
            store = self.make_store(root)
            job = store.create("verify", {"path": str(source), "limit": 2})

            completed = execute_job(store, job.job_id)
            self.assertEqual(completed.status, "completed")
            result_path = store.root / job.job_id / "results.json"
            self.assertEqual(len(json.loads(result_path.read_text())), 2)

            resumed = execute_job(store, job.job_id)
            self.assertEqual(resumed.completed_steps, completed.completed_steps)
            self.assertEqual(len(json.loads(result_path.read_text())), 2)

    def test_invalid_verify_path_marks_job_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            job = store.create("verify", {"path": str(root / "missing")})
            with self.assertRaises(Exception):
                execute_job(store, job.job_id)
            self.assertEqual(store.load(job.job_id).status, "failed")

    def test_copy_job_preserves_paths_and_verifies_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            destination = root / "destination"
            (source / "photos").mkdir(parents=True)
            (source / "photos" / "one.jpg").write_bytes(b"one")
            (source / "photos" / "two.jpg").write_bytes(b"two")
            store = self.make_store(root)
            job = store.create("copy", {
                "source_root": str(source), "source_device": "/dev/source",
                "destination": str(destination), "paths": ["photos"]
            })
            with patch("fnos_rescue.executors.inspect_destination", return_value=self.ready_destination(destination)), patch(
                "fnos_rescue.executors.assert_destination_not_source"
            ):
                completed = execute_job(store, job.job_id)
            self.assertEqual(completed.status, "completed")
            self.assertEqual((destination / "photos" / "one.jpg").read_bytes(), b"one")
            self.assertEqual(len(completed.completed_steps), 2)

    def test_copy_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.mkdir()
            store = self.make_store(root)
            job = store.create("copy", {
                "source_root": str(source), "source_device": "/dev/source",
                "destination": str(root / "out"), "paths": ["../case"]
            })
            with self.assertRaises(Exception):
                execute_job(store, job.job_id)
            self.assertEqual(store.load(job.job_id).status, "failed")

    def test_pause_then_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.mkdir()
            (source / "one.txt").write_text("one")
            store = self.make_store(root)
            job = store.create("copy", {
                "source_root": str(source), "source_device": "/dev/source",
                "destination": str(root / "out"), "paths": ["one.txt"]
            })
            store.request_control(job, "pause")
            with patch("fnos_rescue.executors.inspect_destination", return_value=self.ready_destination(root / "out")), patch(
                "fnos_rescue.executors.assert_destination_not_source"
            ):
                self.assertEqual(execute_job(store, job.job_id).status, "paused")
                store.request_control(store.load(job.job_id), "resume")
                self.assertEqual(execute_job(store, job.job_id).status, "completed")

    def test_copy_rejects_source_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            selected = source / "selected"
            selected.mkdir(parents=True)
            outside = root / "outside.txt"
            outside.write_text("secret")
            (selected / "link.txt").symlink_to(outside)
            store = self.make_store(root)
            job = store.create("copy", {
                "source_root": str(source), "source_device": "/dev/source",
                "destination": str(root / "out"), "paths": ["selected"]
            })
            with self.assertRaises(Exception):
                execute_job(store, job.job_id)

    def test_copy_rejects_target_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.mkdir()
            (source / "one.txt").write_text("safe")
            destination = root / "out"
            destination.mkdir()
            outside = root / "outside.txt"
            outside.write_text("unchanged")
            (destination / "one.txt").symlink_to(outside)
            store = self.make_store(root)
            job = store.create("copy", {
                "source_root": str(source), "source_device": "/dev/source",
                "destination": str(destination), "paths": ["one.txt"]
            })
            with patch("fnos_rescue.executors.inspect_destination", return_value=self.ready_destination(destination)), patch(
                "fnos_rescue.executors.assert_destination_not_source"
            ):
                with self.assertRaises(Exception):
                    execute_job(store, job.job_id)
            self.assertEqual(outside.read_text(), "unchanged")

    def test_failed_copy_is_retried_instead_of_marked_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.mkdir()
            (source / "one.txt").write_text("retry me")
            destination = root / "out"
            store = self.make_store(root)
            job = store.create("copy", {
                "source_root": str(source), "source_device": "/dev/source",
                "destination": str(destination), "paths": ["one.txt"]
            })
            safety = patch("fnos_rescue.executors.assert_destination_not_source")
            facts = patch(
                "fnos_rescue.executors.inspect_destination",
                return_value=self.ready_destination(destination),
            )
            with safety, facts, patch(
                "fnos_rescue.executors.os.write", side_effect=OSError(errno.ENOSPC, "disk full")
            ):
                first = execute_job(store, job.job_id)
            self.assertEqual(first.status, "completed_with_errors")
            self.assertEqual(first.completed_steps, [])
            self.assertFalse((destination / "one.txt").exists())
            self.assertEqual(list(destination.glob(".*.tmp")), [])
            with patch("fnos_rescue.executors.assert_destination_not_source"), patch(
                "fnos_rescue.executors.inspect_destination",
                return_value=self.ready_destination(destination),
            ):
                second = execute_job(store, job.job_id)
            self.assertEqual(second.status, "completed_with_errors")
            self.assertEqual(second.completed_steps, ["one.txt"])

    def test_restart_recopies_file_if_power_loss_precedes_step_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.mkdir()
            (source / "one.txt").write_text("durable")
            destination = root / "out"
            store = self.make_store(root)
            job = store.create("copy", {
                "source_root": str(source), "source_device": "/dev/source",
                "destination": str(destination), "paths": ["one.txt"],
            })
            with patch("fnos_rescue.executors.inspect_destination", return_value=self.ready_destination(destination)), patch(
                "fnos_rescue.executors.assert_destination_not_source"
            ), patch.object(store, "complete_step", side_effect=RuntimeError("simulated power loss")):
                with self.assertRaisesRegex(RuntimeError, "power loss"):
                    execute_job(store, job.job_id)
            self.assertEqual((destination / "one.txt").read_text(), "durable")
            self.assertEqual(store.load(job.job_id).completed_steps, [])
            with patch("fnos_rescue.executors.inspect_destination", return_value=self.ready_destination(destination)), patch(
                "fnos_rescue.executors.assert_destination_not_source"
            ):
                completed = execute_job(store, job.job_id)
            self.assertEqual(completed.status, "completed")
            self.assertEqual(completed.completed_steps, ["one.txt"])

    def test_copy_rejects_source_directory_swapped_to_symlink_after_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            selected = source / "selected"
            selected.mkdir(parents=True)
            (selected / "one.txt").write_text("safe")
            outside = root / "outside"
            outside.mkdir()
            (outside / "one.txt").write_text("secret")
            destination = root / "out"
            store = self.make_store(root)
            job = store.create("copy", {
                "source_root": str(source), "source_device": "/dev/source",
                "destination": str(destination), "paths": ["selected"],
            })

            def swap_then_inspect(_path):
                selected.rename(source / "selected-original")
                selected.symlink_to(outside, target_is_directory=True)
                return self.ready_destination(destination)

            with patch("fnos_rescue.executors.inspect_destination", side_effect=swap_then_inspect), patch(
                "fnos_rescue.executors.assert_destination_not_source"
            ):
                completed = execute_job(store, job.job_id)
            self.assertEqual(completed.status, "completed_with_errors")
            self.assertFalse((destination / "selected" / "one.txt").exists())

    def test_worker_lock_rejects_concurrent_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            job = store.create("verify", {"path": str(root)})
            with _job_lock(store, job.job_id):
                with self.assertRaises(Exception):
                    execute_job(store, job.job_id)

    def test_stale_starting_worker_can_restart_after_reboot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            job = store.create("verify", {"path": str(root)})
            store.transition(job, "starting")
            (store.root / job.job_id / "worker.pid").write_text("999999999\n")
            with patch("fnos_rescue.executors.subprocess.Popen", return_value=Mock(pid=4321)):
                pid = start_background(store, job)
            self.assertEqual(pid, 4321)
            events = (store.root / job.job_id / "progress.jsonl").read_text()
            self.assertIn("worker.stale", events)


if __name__ == "__main__":
    unittest.main()
