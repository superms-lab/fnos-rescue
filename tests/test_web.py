import io
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fnos_rescue.devices import DeviceFacts
from fnos_rescue.cases import RecoveryCase
from fnos_rescue.errors import RescueError
from fnos_rescue.web import RescueWebHandler, _human_size, _read_inventory, _require_case_cache, _require_web_root, case_directory, list_devices, load_access_token, serve, validate_web_job
from fnos_rescue.jobs import JobStore


class WebTests(unittest.TestCase):
    def test_web_root_follows_symlinks_before_containment_check(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            allowed = root / "allowed"
            allowed.mkdir()
            (allowed / "inside").mkdir()
            (allowed / "escape").symlink_to(outside)
            with patch.dict("os.environ", {"FNOS_RESCUE_WEB_ROOTS": str(allowed)}):
                self.assertEqual(_require_web_root(allowed / "inside"), (allowed / "inside").resolve())
                with self.assertRaises(ValueError):
                    _require_web_root(allowed / "escape")

    def test_chunk_cache_is_rebuilt_from_validated_job_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = RecoveryCase.create(DeviceFacts(
                path="/dev/sda", name="sda", size_bytes=1000, read_only=True,
                device_type="disk", filesystem="btrfs", model="test", serial="SERIAL",
                uuid="1" * 32, mountpoints=(),
            ))
            case_path = root / case.case_id
            case.save(case_path)
            store = JobStore(case_path)
            job = store.create("btrfs-chunk-cache", {})
            cache = store.root / job.job_id / "chunk-mappings.cache"
            cache.write_bytes(b"cache")
            store.transition(job, "completed")
            self.assertEqual(_require_case_cache(case_path, cache), str(cache.resolve()))
            with self.assertRaises(ValueError):
                _require_case_cache(case_path, store.root / job.job_id / "../chunk-mappings.cache")

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
        handler.server = Mock(access_token="test-token")
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
        handler.server = Mock(access_token="test-token")
        handler.rfile = io.BytesIO(payload)
        handler._json = Mock()
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0], 400)

    def test_post_rejects_missing_session_token(self):
        handler = object.__new__(RescueWebHandler)
        handler.path = "/api/protect"
        handler.headers = {"Content-Length": "2", "Host": "localhost:8790"}
        handler.server = Mock(access_token="required-token")
        handler.rfile = io.BytesIO(b"{}")
        handler._json = Mock()
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0], 401)

    def test_get_rejects_missing_access_token(self):
        handler = object.__new__(RescueWebHandler)
        handler.path = "/api/cases"
        handler.headers = {"Host": "localhost:8790"}
        handler.server = Mock(access_token="required-token")
        handler._json = Mock()
        handler.do_GET()
        self.assertEqual(handler._json.call_args.args[0], 401)

    def test_access_token_file_is_private_and_nontrivial(self):
        with tempfile.TemporaryDirectory() as temporary:
            token = Path(temporary) / "web.token"
            token.write_text("x" * 32)
            token.chmod(0o600)
            self.assertEqual(load_access_token(token), "x" * 32)
            token.chmod(0o644)
            with self.assertRaises(RescueError):
                load_access_token(token)

    def test_server_refuses_non_loopback_listener(self):
        with self.assertRaises(RescueError):
            serve("0.0.0.0", 8790)

    def test_job_device_must_match_case_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = RecoveryCase.create(DeviceFacts(
                path="/dev/sda", name="sda", size_bytes=1000, read_only=True,
                device_type="disk", filesystem="btrfs", model="test", serial="SERIAL",
                uuid="1" * 32, mountpoints=(),
            ))
            case_path = root / case.case_id
            case.save(case_path)
            with patch("fnos_rescue.web.assert_case_source", side_effect=ValueError("wrong source")):
                with self.assertRaises(ValueError):
                    validate_web_job(case_path, "btrfs-probe", {"device": "/dev/sdb"})

    def test_web_rejects_arbitrary_recovery_tool_path(self):
        handler = object.__new__(RescueWebHandler)
        handler.path = "/api/jobs"
        payload = json.dumps({
            "case_id": "case-111111111111",
            "kind": "btrfs-root-scan",
            "parameters": {"device": "/dev/sda", "fsid": "1" * 32, "scanner": "/tmp/tool"},
        }).encode()
        handler.headers = {"Content-Length": str(len(payload)), "Host": "localhost:8790", "X-FNOS-Token": "test-token"}
        handler.server = Mock(access_token="test-token")
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

    def test_inventory_decodes_base64_paths_without_tsv_ambiguity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "inventory.tsv"
            special = b"Photos/tab\tline\nraw-\xff.jpg"
            encoded = base64.b64encode(special).decode("ascii")
            escape = base64.b64encode(b"../escape").decode("ascii")
            path.write_text(
                "rootid\tobjectid\tsize\tpath_b64\n"
                f"257\t9\t4\t{encoded}\n"
                f"257\t10\t4\t{escape}\n"
            )
            items = _read_inventory(path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["path_b64"], encoded)
        self.assertEqual(items[0]["path"], "Photos/tab\\x09line\\x0araw-\\xff.jpg")

    def test_inventory_exposes_only_regular_files_for_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "inventory.tsv"
            file_path = base64.b64encode(b"Photos/a.jpg").decode()
            directory = base64.b64encode(b"Photos").decode()
            path.write_text(
                "rootid\ttype\tsize\tobjectid\tpath_b64\n"
                f"257\t2\t0\t256\t{directory}\n"
                f"257\t1\t4\t9\t{file_path}\n"
            )
            items = _read_inventory(path)
        self.assertEqual([item["path"] for item in items], ["Photos/a.jpg"])


if __name__ == "__main__":
    unittest.main()
