import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "packaging/fnos/fnos-rescue-helper"


class FnosHelperTests(unittest.TestCase):
    def test_rejects_job_and_shell_execution(self):
        for command in ("job-run", "job-control", "case-report", "sh", "bash", "python3"):
            result = subprocess.run([str(HELPER), command], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, command)
            self.assertIn("not allowed", result.stderr)

    def test_allowlist_contains_only_fixed_diagnostic_commands(self):
        helper = HELPER.read_text()
        self.assertIn("protect", helper)
        self.assertIn("fnos-quiesce-plan", helper)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", helper)
        self.assertNotIn("job-run", helper)
        self.assertNotIn("job-control", helper)


if __name__ == "__main__":
    unittest.main()
