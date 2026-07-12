import unittest
from unittest.mock import patch

from fnos_rescue.doctor import CORE_TOOLS, RECOVERY_TOOLS, diagnose


class DoctorTests(unittest.TestCase):
    def test_linux_with_all_tools_is_ready(self) -> None:
        with patch("fnos_rescue.doctor.platform.system", return_value="Linux"), patch(
            "fnos_rescue.doctor.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"
        ):
            report = diagnose()
        self.assertTrue(report.ok)
        self.assertEqual(set(report.core_tools), set(CORE_TOOLS))
        self.assertEqual(set(report.recovery_tools), set(RECOVERY_TOOLS))

    def test_reports_platform_and_missing_tools(self) -> None:
        with patch("fnos_rescue.doctor.platform.system", return_value="Darwin"), patch(
            "fnos_rescue.doctor.shutil.which", return_value=None
        ):
            report = diagnose()
        self.assertFalse(report.ok)
        self.assertIn("raw-device recovery requires Linux", report.problems)
        self.assertTrue(any("missing core tools" in problem for problem in report.problems))


if __name__ == "__main__":
    unittest.main()
