import tempfile
import unittest
from pathlib import Path

from fnos_rescue.jobs import JobStore
from fnos_rescue.reports import case_report


class ReportTests(unittest.TestCase):
    def test_case_report_counts_jobs_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary) / "case"
            case.mkdir()
            (case / "case.json").write_text("{}\n")
            store = JobStore(case)
            job = store.create("verify", {})
            store.record_failure(job, "bad", "broken")
            store.transition(job, "completed_with_errors")
            report = case_report(case)
            self.assertEqual(report["jobs"], 1)
            self.assertEqual(report["failure_records"], 1)
            self.assertTrue(report["ready"])


if __name__ == "__main__":
    unittest.main()
