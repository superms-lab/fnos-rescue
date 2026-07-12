import json
import tempfile
import unittest
from pathlib import Path

from fnos_rescue.jobs import JobStore


class JobStoreTests(unittest.TestCase):
    def make_case(self, root: Path) -> Path:
        case = root / "case"
        case.mkdir()
        (case / "case.json").write_text("{}\n")
        return case

    def test_job_progress_survives_reload_and_skips_completed_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = JobStore(self.make_case(Path(temporary)))
            job = store.create("extract", {"paths": ["photos"]})
            store.transition(job, "running", current_step="scan")
            store.complete_step(job, "scan", {"items": 12})

            loaded = store.load(job.job_id)
            self.assertEqual(loaded.status, "running")
            self.assertEqual(store.pending_steps(loaded, ["scan", "copy", "verify"]), ["copy", "verify"])
            events = (store.root / job.job_id / "progress.jsonl").read_text().splitlines()
            self.assertEqual([json.loads(line)["event"] for line in events], [
                "job.created", "job.running", "step.completed"
            ])

    def test_failure_manifest_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = JobStore(self.make_case(Path(temporary)))
            job = store.create("extract", {})
            store.record_failure(job, "broken.jpg", "checksum mismatch")
            store.record_failure(job, "missing.mov", "not found")
            failures = (store.root / job.job_id / "failures.jsonl").read_text().splitlines()
            self.assertEqual(len(failures), 2)
            self.assertEqual(json.loads(failures[0])["item"], "broken.jpg")

    def test_rejects_job_id_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = JobStore(self.make_case(Path(temporary)))
            with self.assertRaises(Exception):
                store.load("../../outside")


if __name__ == "__main__":
    unittest.main()
