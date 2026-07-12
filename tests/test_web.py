import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fnos_rescue.devices import DeviceFacts
from fnos_rescue.web import RescueWebHandler, _human_size, _read_inventory, case_directory, list_devices


class WebTests(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(_human_size(4_000_000_000_000), "4.00 TB")

    @patch("fnos_rescue.web.platform.system", return_value="Darwin")
    def test_device_list_is_empty_off_linux(self, _system):
        self.assertEqual(list_devices(), [])

    @patch("fnos_rescue.web.platform.system", return_value="Linux")
    @patch("fnos_rescue.web.run")
    def test_lists_top_level_disks(self, run, _system):
        run.return_value.stdout = json.dumps({"blockdevices": [{"name": "sda", "path": "/dev/sda", "size": 1000, "ro": 1, "type": "disk", "fstype": "btrfs", "mountpoints": [None]}]})
        devices = list_devices()
        self.assertEqual(devices[0]["path"], "/dev/sda")
        self.assertTrue(devices[0]["read_only"])

    def test_post_rejects_non_device_path_before_protect(self):
        handler = object.__new__(RescueWebHandler)
        handler.path = "/api/protect"
        handler.headers = {"Content-Length": "36", "Host": "localhost:8790", "X-FNOS-Token": "test-token"}
        handler.server = Mock(csrf_token="test-token")
        handler.rfile = io.BytesIO(b'{"device":"/tmp/a","serial":"secret"}')
        handler._json = Mock()
        with patch("fnos_rescue.web.protect_source") as protect:
            handler.do_POST()
        protect.assert_not_called()
        self.assertEqual(handler._json.call_args.args[0], 400)

    def test_case_directory_rejects_traversal(self):
        with self.assertRaises(ValueError):
            case_directory("../../etc")

    def test_web_job_allowlist_rejects_arbitrary_kind(self):
        handler = object.__new__(RescueWebHandler)
        handler.path = "/api/jobs"
        payload = b'{"case_id":"case-111111111111","kind":"shell","parameters":{}}'
        handler.headers = {"Content-Length": str(len(payload)), "Host": "localhost:8790"}
        handler.headers["X-FNOS-Token"] = "test-token"
        handler.server = Mock(csrf_token="test-token")
        handler.rfile = io.BytesIO(payload)
        handler._json = Mock()
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0], 400)

    def test_post_rejects_missing_session_token(self):
        handler = object.__new__(RescueWebHandler)
        handler.path = "/api/protect"
        handler.headers = {"Content-Length": "2", "Host": "localhost:8790"}
        handler.server = Mock(csrf_token="required-token")
        handler.rfile = io.BytesIO(b"{}")
        handler._json = Mock()
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0], 403)

    def test_web_rejects_arbitrary_recovery_tool_path(self):
        handler = object.__new__(RescueWebHandler)
        handler.path = "/api/jobs"
        payload = json.dumps({
            "case_id": "case-111111111111",
            "kind": "btrfs-root-scan",
            "parameters": {"device": "/dev/sda", "fsid": "1" * 32, "scanner": "/tmp/tool"},
        }).encode()
        handler.headers = {"Content-Length": str(len(payload)), "Host": "localhost:8790", "X-FNOS-Token": "test-token"}
        handler.server = Mock(csrf_token="test-token")
        handler.rfile = io.BytesIO(payload)
        handler._json = Mock()
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0], 400)
        self.assertIn("not allowed", handler._json.call_args.args[1]["error"])

    def test_inventory_rejects_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "inventory.tsv"
            path.write_text("rootid\tobjectid\tsize\tpath\n257\t9\t4\tPhotos/a.jpg\n257\t10\t4\t../escape\n")
            items = _read_inventory(path)
        self.assertEqual([item["path"] for item in items], ["Photos/a.jpg"])
        self.assertEqual(items[0]["inode"], "9")


if __name__ == "__main__":
    unittest.main()
