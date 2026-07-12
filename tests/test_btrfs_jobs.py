import tempfile
import unittest
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


class BtrfsJobTests(unittest.TestCase):
    def make_store(self, root: Path) -> JobStore:
        case = root / "case"
        case.mkdir()
        (case / "case.json").write_text("{}\n")
        return JobStore(case)

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
            scanner = root / "scanner"
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
            result = CommandResult((str(scanner), "/dev/test"), 0, "ROOT 123\n", "")
            with patch("fnos_rescue.btrfs_jobs.require_block_device", return_value=Path("/dev/test")), patch(
                "fnos_rescue.btrfs_jobs.assert_read_only"
            ), patch("fnos_rescue.btrfs_jobs.run", return_value=result):
                completed = execute_btrfs_root_scan(store, job)
            self.assertEqual(completed.status, "completed")
            self.assertEqual((store.root / job.job_id / "root-scan.log").read_text(), "ROOT 123\n")
            self.assertEqual(_scan_argv(parameters, Path("/dev/test"))[-2:], ["1", "2"])

    def test_root_scan_rejects_invalid_fsid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner = Path(temporary) / "scanner"
            scanner.write_text("x")
            scanner.chmod(0o700)
            with self.assertRaises(Exception):
                _scan_argv({"scanner": str(scanner), "fsid": "not-an-fsid"}, Path("/dev/test"))

    def private_tool(self, root: Path) -> Path:
        tool = root / "btrfs"
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o700)
        return tool

    def test_chunk_cache_job_requires_created_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.make_store(root)
            job = store.create("btrfs-chunk-cache", {
                "device": "/dev/test", "private_btrfs": str(self.private_tool(root))
            })
            def fake_run(*_args, **kwargs):
                Path(kwargs["env"]["BTRFS_CHUNK_CACHE_SAVE"]).write_text("chunk\n")
                return CommandResult(("btrfs",), 0, "Saved 1 chunk mappings\n", "")
            with patch("fnos_rescue.btrfs_jobs.require_block_device", return_value=Path("/dev/test")), patch(
                "fnos_rescue.btrfs_jobs.assert_read_only"
            ), patch("fnos_rescue.btrfs_jobs.run", side_effect=fake_run):
                completed = execute_btrfs_chunk_cache(store, job)
            self.assertEqual(completed.status, "completed")

    def test_list_and_extract_jobs_write_private_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.make_store(root)
            tool = self.private_tool(root)
            cache = root / "cache"
            cache.write_text("chunk\n")
            common = {
                "device": "/dev/test", "private_btrfs": str(tool),
                "chunk_cache": str(cache), "filesystem_root": 4096,
            }
            list_job = store.create("btrfs-list", common)
            extract_job = store.create("btrfs-extract-inode", {
                **common, "rootid": 257, "inode": 123, "expected_size": 4,
            })
            def fake_run(*_args, **kwargs):
                env = kwargs["env"]
                if "BTRFS_LIST_PATHS" in env:
                    Path(env["BTRFS_LIST_PATHS"]).write_text("rootid\tpath\n257\t/a\n")
                if "BTRFS_EXTRACT_PATH" in env:
                    Path(env["BTRFS_EXTRACT_PATH"]).write_bytes(b"data")
                return CommandResult(("btrfs",), 0, "ok\n", "")
            with patch("fnos_rescue.btrfs_jobs.require_block_device", return_value=Path("/dev/test")), patch(
                "fnos_rescue.btrfs_jobs.assert_read_only"
            ), patch("fnos_rescue.btrfs_jobs.run", side_effect=fake_run):
                self.assertEqual(execute_btrfs_list(store, list_job).status, "completed")
                self.assertEqual(execute_btrfs_extract_inode(store, extract_job).status, "completed")
            self.assertTrue((store.root / list_job.job_id / "btrfs-files.tsv").is_file())
            self.assertEqual((store.root / extract_job.job_id / "extracted.bin").read_bytes(), b"data")

    def test_batch_extract_preserves_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.make_store(root)
            tool = self.private_tool(root)
            cache = root / "cache"
            cache.write_text("chunk\n")
            job = store.create("btrfs-extract-batch", {
                "device": "/dev/test", "private_btrfs": str(tool),
                "chunk_cache": str(cache), "filesystem_root": 4096,
                "items": [{"path": "Photos/a.jpg", "rootid": 257, "inode": 9, "expected_size": 4}],
            })
            def fake_run(*_args, **kwargs):
                Path(kwargs["env"]["BTRFS_EXTRACT_PATH"]).write_bytes(b"data")
                return CommandResult(("btrfs",), 0, "", "")
            with patch("fnos_rescue.btrfs_jobs.require_block_device", return_value=Path("/dev/test")), patch(
                "fnos_rescue.btrfs_jobs.assert_read_only"
            ), patch("fnos_rescue.btrfs_jobs.run_interruptible", side_effect=fake_run):
                completed = execute_btrfs_extract_batch(store, job)
            self.assertEqual(completed.status, "completed")
            self.assertTrue((store.root / job.job_id / "extracted" / "Photos" / "a.jpg").is_file())


if __name__ == "__main__":
    unittest.main()
