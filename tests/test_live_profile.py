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
        self.assertIn("ReadWritePaths=/var/lib/fnos-rescue", service)
        kiosk = (ROOT / "live/config/includes.chroot/etc/systemd/system/fnos-rescue-kiosk.service").read_text()
        self.assertIn("User=user", kiosk)
        self.assertIn("openbox-session", kiosk)
        ready = (ROOT / "live/config/includes.chroot/etc/systemd/system/fnos-rescue-ready.service").read_text()
        self.assertIn("live-ready.sh", ready)
        smoke = (ROOT / "scripts/test-live-iso.sh").read_text()
        self.assertIn("boot_and_check bios", smoke)
        self.assertIn("boot_and_check uefi", smoke)
        self.assertIn("FNOS_RESCUE_READY", smoke)

    def test_windows_helper_has_no_mutating_disk_commands(self):
        helper = (ROOT / "scripts/windows/inspect-wsl.ps1").read_text().lower()
        for forbidden in ("wsl.exe --mount", "initialize-disk", "format-volume", "set-disk"):
            self.assertNotIn(forbidden, helper)

    def test_live_builder_pins_debian_mirrors(self):
        builder = (ROOT / "scripts/build-live-iso.sh").read_text()
        self.assertIn("--ignore-system-defaults", builder)
        self.assertIn("--mode debian", builder)
        self.assertIn('--keyring-packages "debian-archive-keyring"', builder)
        self.assertIn("--security false", builder)
        security = (ROOT / "live/config/archives/debian-security.list.chroot").read_text()
        self.assertIn("bookworm-security", security)
        self.assertIn('--mirror-bootstrap "https://deb.debian.org/debian"', builder)
        self.assertIn('--mirror-chroot-security "https://security.debian.org/debian-security"', builder)

    def test_ci_pins_debian_live_build_source(self):
        workflow = (ROOT / ".github/workflows/live-iso.yml").read_text()
        self.assertIn("salsa.debian.org/live-team/live-build.git", workflow)
        self.assertIn("37c453337996a3f9cbf80697e2321d8162369776", workflow)

    def test_private_btrfs_build_disables_unneeded_convert(self):
        builder = (ROOT / "scripts/build-recovery-tools.sh").read_text()
        self.assertIn("--disable-convert", builder)

    def test_web_source_contains_no_demo_devices(self):
        source = (ROOT / "web/src/main.jsx").read_text()
        for forbidden in ("fallbackDevices", "DEMO-", "Sample destination", "安全演示模式"):
            self.assertNotIn(forbidden, source)
        self.assertIn("未发现可操作的真实块设备", source)
        self.assertIn("本机服务未连接", source)


if __name__ == "__main__":
    unittest.main()
