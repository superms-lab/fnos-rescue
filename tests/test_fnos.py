import unittest
from unittest.mock import patch

from fnos_rescue.fnos import detect_fnos, quiesce_plan
from fnos_rescue.runner import CommandResult


class FnosTests(unittest.TestCase):
    def test_detects_markers_and_active_services(self) -> None:
        def exists(path):
            return str(path) in {"/fs", "/var/apps", "/usr/local/apps"}

        with patch("fnos_rescue.fnos.Path.exists", exists), patch(
            "fnos_rescue.fnos.Path.is_dir", return_value=True
        ), patch("fnos_rescue.fnos.run", return_value=CommandResult(("systemctl",), 0, "active\n", "")):
            environment = detect_fnos()
        self.assertTrue(environment.detected)
        self.assertEqual(environment.app_root, "/var/apps/fnos-rescue")

    def test_quiesce_is_plan_only(self) -> None:
        with patch("fnos_rescue.fnos.detect_fnos") as detect, patch(
            "fnos_rescue.fnos.run",
            return_value=CommandResult(("lsblk",), 0, "/dev/test /vol1\n", ""),
        ):
            detect.return_value.detected = True
            detect.return_value.active_services = ("smbd.service",)
            plan = quiesce_plan("/dev/test")
        self.assertTrue(plan["dry_run"])
        self.assertIn("smbd.service", plan["services_to_stop"])


if __name__ == "__main__":
    unittest.main()
