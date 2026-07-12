import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LiveProfileTests(unittest.TestCase):
    def test_profile_has_recovery_tools_and_local_only_web(self):
        packages = (ROOT / "live/config/package-lists/fnos-rescue.list.chroot").read_text().splitlines()
        self.assertTrue({"btrfs-progs", "gddrescue", "testdisk", "qemu-utils"}.issubset(packages))
        service = (ROOT / "live/config/includes.chroot/etc/systemd/system/fnos-rescue-web.service").read_text()
        self.assertIn("--host 127.0.0.1", service)
        self.assertIn("ProtectSystem=strict", service)
        kiosk = (ROOT / "live/config/includes.chroot/etc/systemd/system/fnos-rescue-kiosk.service").read_text()
        self.assertIn("User=user", kiosk)
        self.assertIn("openbox-session", kiosk)

    def test_windows_helper_has_no_mutating_disk_commands(self):
        helper = (ROOT / "scripts/windows/inspect-wsl.ps1").read_text().lower()
        for forbidden in ("wsl.exe --mount", "initialize-disk", "format-volume", "set-disk"):
            self.assertNotIn(forbidden, helper)

    def test_live_builder_pins_debian_mirrors(self):
        builder = (ROOT / "scripts/build-live-iso.sh").read_text()
        self.assertIn('--mirror-bootstrap "https://deb.debian.org/debian"', builder)
        self.assertIn('--mirror-chroot-security "https://security.debian.org/debian-security"', builder)


if __name__ == "__main__":
    unittest.main()
