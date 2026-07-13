import tempfile
import unittest
import hashlib
import json
import base64
from pathlib import Path
from unittest.mock import patch

from fnos_rescue.btrfs_jobs import (
    _scan_argv,
    execute_btrfs_chunk_cache,
    execute_btrfs_extract_inode,
    execute_btrfs_extract_batch,
    execute_btrfs_list,
    execute_btrfs_probe,
    execute_btrfs_root_scan,
)
from fnos_rescue.jobs import JobStore
from fnos_rescue.runner import CommandResult
from fnos_rescue.web import _read_inventory


class BtrfsJobTests(unittest.TestCase):
    FSID = "11111111222233334444555555555555"

    def make_store(self, root: Path) -> JobStore:
        case = root / "case"
        case.mkdir()
        (case / "case.json").write_text(json.dumps({
            "case_id": "case-test000001",
            "created_at": "2026-01-01T00:00:00+00:00",
            "source": {"path": "/dev/test", "serial": "SERIAL", "size_bytes": 1048576, "uuid": None},
        }) + "\n")
        return JobStore(case)

    def make_cache_and_roots(self, store: JobStore, tool: Path) -> Path:
        cache_job = store.create("btrfs-chunk-cache", {"device": "/dev/test", "fsid": self.FSID})
        cache = store.root / cache_job.job_id / "chunk-mappings.cache"
        cache.write_bytes(b"chunk\n")
        cache.with_name(cache.name + ".manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "case_id": "case-test000001",
            "fsid": self.FSID,
            "source": {"path": "/dev/test", "serial": "SERIAL", "size_bytes": 1048576, "uuid": None},
            "recovery_layer": "/dev/test",
            "cache": {"path": str(cache), "bytes": cache.stat().st_size,
                      "sha256": hashlib.sha256(cache.read_bytes()).hexdigest()},
            "tool": {"path": str(tool), "sha256": hashlib.sha256(tool.read_bytes()).hexdigest(),
                     "package_version": "0.1.3"},
        }))
        store.transition(cache_job, "completed")
        scan_job = store.create("btrfs-root-scan", {"device": "/dev/test", "fsid": self.FSID})
        candidate_path = store.root / scan_job.job_id / "root-candidates.json"
        candidate_path.write_text(json.dumps({
            "schema_version": 1, "fsid": self.FSID, "candidates": [{
                "fsid": self.FSID, "logical": 4096, "generation": 99, "owner": 5,
                "level": 1, "nritems": 3, "kind": "filesystem_tree", "physical_copies": [8192],
            }],
        }))
        (store.root / scan_job.job_id / "root-scan.json").write_text(json.dumps({
            "candidate_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        }))
        store.transition(scan_job, "completed")
        return cache

    def test_probe_writes_superblock_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self.make_store(Path(temporary))
            job = store.create("btrfs-probe", {"device": "/dev/test"})
            evidence = {"plugin": "fnos-btrfs", "mirrors": [{}, {}, {}]}
            with patch("fnos_rescue.btrfs_jobs.FnosBtrfsPlugin.probe", return_value=evidence):
                completed = execute_btrfs_probe(store, job)
            self.assertEqual(completed.status, "completed")
            self.assertTrue((store.root / job.job_id / "superblocks.json").is_file())

    def test_root_scan_requires_valid_ranges_and_writes_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.make_store(root)
            scanner = root / "scan_btrfs_roots"
            scanner.write_text("#!/bin/sh\n")
            scanner.chmod(0o700)
            parameters = {
                "device": "/dev/test",
                "scanner": str(scanner),
                "fsid": "11111111-2222-3333-4444-555555555555",
                "start_gib": 1,
                "end_gib": 2,
            }
            job = store.create("btrfs-root-scan", parameters)
            result = CommandResult(
                (str(scanner), "/dev/test"), 0,
                "FS_CANDIDATE physical=8192 logical=4096 generation=99 owner=5 nritems=3 level=1\n",
                "",
            )
            def fake_scan(*_args, **kwargs):
                Path(kwargs["stdout_path"]).write_text(result.stdout)
                Path(kwargs["stderr_path"]).write_text(result.stderr)
                return result
            with patch("fnos_rescue.btrfs_jobs.TRUSTED_TOOL_ROOTS", (root,)), patch("fnos_rescue.btrfs_jobs.require_block_device", return_value=Path("/dev/test")), patch(
                "fnos_rescue.btrfs_jobs.assert_read_only"
            ), patch("fnos_rescue.btrfs_jobs.run_streaming", side_effect=fake_scan):
                completed = execute_btrfs_root_scan(store, job)
            self.assertEqual(completed.status, "completed")
            self.assertIn("FS_CANDIDATE", (store.root / job.job_id / "root-scan.log").read_text())
            candidate_data = json.loads((store.root / job.job_id / "root-candidates.json").read_text())
            self.assertEqual(candidate_data["candidates"][0]["owner"], 5)
            with patch("fnos_rescue.btrfs_jobs.TRUSTED_TOOL_ROOTS", (root,)):
                self.assertEqual(_scan_argv(parameters, Path("/dev/test"))[-2:], ["1", "2"])

    def test_root_scan_rejects_invalid_fsid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner = Path(temporary) / "scan_btrfs_roots"
            scanner.write_text("x")
            scanner.chmod(0o700)
            with patch("fnos_rescue.btrfs_jobs.TRUSTED_TOOL_ROOTS", (Path(temporary),)), self.assertRaises(Exception):
                _scan_argv({"scanner": str(scanner), "fsid": "not-an-fsid"}, Path("/dev/test"))

    def private_tool(self, root: Path) -> Path:
        tool = root / "fnos-rescue-btrfs"
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o700)
        return tool

    def test_chunk_cache_job_requires_created_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.make_store(root)
            job = store.create("btrfs-chunk-cache", {
                "device": "/dev/test", "private_btrfs": str(self.private_tool(root)),
                "fsid": self.FSID,
            })
            def fake_run(*_args, **kwargs):
                Path(kwargs["env"]["BTRFS_CHUNK_CACHE_SAVE"]).write_text("chunk\n")
                Path(kwargs["stdout_path"]).write_text("Saved 1 chunk mappings\n")
                Path(kwargs["stderr_path"]).write_text("")
                return CommandResult(("btrfs",), 0, "Saved 1 chunk mappings\n", "")
            with patch("fnos_rescue.btrfs_jobs.TRUSTED_TOOL_ROOTS", (root,)), patch("fnos_rescue.btrfs_jobs.require_block_device", return_value=Path("/dev/test")), patch(
                "fnos_rescue.btrfs_jobs.assert_read_only"
            ), patch("fnos_rescue.btrfs_jobs.run_streaming", side_effect=fake_run):
                completed = execute_btrfs_chunk_cache(store, job)
            self.assertEqual(completed.status, "completed")

    def test_list_and_extract_jobs_write_private_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.make_store(root)
            tool = self.private_tool(root)
            cache = self.make_cache_and_roots(store, tool)
            common = {
                "device": "/dev/test", "private_btrfs": str(tool),
                "chunk_cache": str(cache), "filesystem_root": 4096,
            }
            list_job = store.create("btrfs-list", common)
            extract_job = store.create("btrfs-extract-inode", {
                **common, "rootid": 257, "inode": 123, "expected_size": 4,
                "expected_sha256": hashlib.sha256(b"data").hexdigest(),
            })
            def fake_run(*_args, **kwargs):
                env = kwargs["env"]
                Path(kwargs["stdout_path"]).write_text("ok\n")
                Path(kwargs["stderr_path"]).write_text("")
                if "BTRFS_LIST_PATHS" in env:
                    Path(env["BTRFS_LIST_PATHS"]).write_text("rootid\tpath\n257\t/a\n")
                if "BTRFS_EXTRACT_PATH" in env:
                    Path(env["BTRFS_EXTRACT_PATH"]).write_bytes(b"data")
                return CommandResult(("btrfs",), 0, "ok\n", "")
            with patch("fnos_rescue.btrfs_jobs.TRUSTED_TOOL_ROOTS", (root,)), patch("fnos_rescue.btrfs_jobs.require_block_device", return_value=Path("/dev/test")), patch(
                "fnos_rescue.btrfs_jobs.assert_read_only"
            ), patch("fnos_rescue.btrfs_jobs.run_streaming", side_effect=fake_run):
                self.assertEqual(execute_btrfs_list(store, list_job).status, "completed")
                self.assertEqual(execute_btrfs_extract_inode(store, extract_job).status, "completed")
            self.assertTrue((store.root / list_job.job_id / "btrfs-files.tsv").is_file())
            self.assertEqual((store.root / extract_job.job_id / "extracted.bin").read_bytes(), b"data")

    def test_batch_extract_preserves_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.make_store(root)
            tool = self.private_tool(root)
            cache = self.make_cache_and_roots(store, tool)
            job = store.create("btrfs-extract-batch", {
                "device": "/dev/test", "private_btrfs": str(tool),
                "chunk_cache": str(cache), "filesystem_root": 4096,
                "items": [{
                    "path": "Photos/a.jpg", "rootid": 257, "inode": 9, "expected_size": 4,
                    "path_b64": base64.b64encode(b"Photos/a.jpg").decode("ascii"),
                    "expected_sha256": hashlib.sha256(b"data").hexdigest(),
                }],
            })
            def fake_run(*_args, **kwargs):
                Path(kwargs["env"]["BTRFS_EXTRACT_PATH"]).write_bytes(b"data")
                return CommandResult(("btrfs",), 0, "", "")
            with patch("fnos_rescue.btrfs_jobs.TRUSTED_TOOL_ROOTS", (root,)), patch("fnos_rescue.btrfs_jobs.require_block_device", return_value=Path("/dev/test")), patch(
                "fnos_rescue.btrfs_jobs.assert_read_only"
            ), patch("fnos_rescue.btrfs_jobs.run_interruptible", side_effect=fake_run):
                completed = execute_btrfs_extract_batch(store, job)
            self.assertEqual(completed.status, "completed")
            self.assertTrue((store.root / job.job_id / "extracted" / "Photos" / "a.jpg").is_file())
            self.assertTrue(completed.completed_steps[0].startswith("257:9:"))

    def test_list_rejects_tampered_cache_and_root_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.make_store(root)
            tool = self.private_tool(root)
            cache = self.make_cache_and_roots(store, tool)
            common = {
                "device": "/dev/test", "private_btrfs": str(tool),
                "chunk_cache": str(cache), "filesystem_root": 4096,
            }
            cache.write_bytes(b"tampered")
            cache_job = store.create("btrfs-list", common)
            with patch("fnos_rescue.btrfs_jobs.TRUSTED_TOOL_ROOTS", (root,)), patch(
                "fnos_rescue.btrfs_jobs.require_block_device", return_value=Path("/dev/test")
            ), patch("fnos_rescue.btrfs_jobs.assert_read_only"), self.assertRaisesRegex(
                Exception, "no longer matches"
            ):
                execute_btrfs_list(store, cache_job)

            cache = self.make_cache_and_roots(store, tool)
            scan_paths = sorted(store.root.glob("job-*/root-candidates.json"))
            for path in scan_paths:
                payload = json.loads(path.read_text())
                payload["candidates"] = []
                path.write_text(json.dumps(payload))
            evidence_job = store.create("btrfs-list", {**common, "chunk_cache": str(cache)})
            with patch("fnos_rescue.btrfs_jobs.TRUSTED_TOOL_ROOTS", (root,)), patch(
                "fnos_rescue.btrfs_jobs.require_block_device", return_value=Path("/dev/test")
            ), patch("fnos_rescue.btrfs_jobs.assert_read_only"), self.assertRaisesRegex(
                Exception, "no matching root-scan evidence"
            ):
                execute_btrfs_list(store, evidence_job)

    def test_web_inventory_to_batch_preserves_special_filename_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.make_store(root)
            tool = self.private_tool(root)
            cache = self.make_cache_and_roots(store, tool)
            raw_path = "Photos/飞牛\t图.jpg".encode()
            inventory_path = root / "inventory.tsv"
            inventory_path.write_text(
                "rootid\ttype\tsize\tobjectid\tpath_b64\n"
                f"257\t1\t4\t9\t{base64.b64encode(raw_path).decode()}\n"
            )
            items = _read_inventory(inventory_path)
            items[0]["expected_sha256"] = hashlib.sha256(b"data").hexdigest()
            job = store.create("btrfs-extract-batch", {
                "device": "/dev/test", "private_btrfs": str(tool),
                "chunk_cache": str(cache), "filesystem_root": 4096, "items": items,
            })

            def fake_run(*_args, **kwargs):
                Path(kwargs["env"]["BTRFS_EXTRACT_PATH"]).write_bytes(b"data")
                return CommandResult(("btrfs",), 0, "", "")

            with patch("fnos_rescue.btrfs_jobs.TRUSTED_TOOL_ROOTS", (root,)), patch(
                "fnos_rescue.btrfs_jobs.require_block_device", return_value=Path("/dev/test")
            ), patch("fnos_rescue.btrfs_jobs.assert_read_only"), patch(
                "fnos_rescue.btrfs_jobs.run_interruptible", side_effect=fake_run
            ):
                completed = execute_btrfs_extract_batch(store, job)
            self.assertEqual(completed.status, "completed")
            self.assertTrue((store.root / job.job_id / "extracted" / "Photos" / "飞牛\t图.jpg").is_file())


if __name__ == "__main__":
    unittest.main()
