import sys
import tempfile
import unittest
from pathlib import Path

from fnos_rescue.errors import JobControlRequested, RescueError
from fnos_rescue.runner import run, run_interruptible, run_streaming


class InterruptibleRunnerTests(unittest.TestCase):
    def test_general_runner_rejects_unapproved_executables(self) -> None:
        with self.assertRaises(RescueError):
            run([sys.executable, "-c", "print('must not run')"])

    def test_streaming_runner_rejects_trusted_executable_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RescueError):
                run_streaming(
                    [sys.executable, "-c", "print('must not run')"],
                    stdout_path=Path(temporary) / "stdout.log",
                    stderr_path=Path(temporary) / "stderr.log",
                    trusted_executable="/definitely/not/python",
                )

    def test_pause_terminates_running_process(self) -> None:
        calls = 0

        def control():
            nonlocal calls
            calls += 1
            return "pause" if calls >= 2 else None

        with self.assertRaises(JobControlRequested) as raised:
            run_interruptible(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                control=control,
                timeout=35,
                poll_interval=0.01,
                trusted_executable=sys.executable,
            )
        self.assertEqual(raised.exception.action, "pause")

    def test_large_stdout_and_stderr_stream_to_disk_without_pipe_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            result = run_streaming(
                [
                    sys.executable,
                    "-c",
                    "import os; os.write(1, b'x' * 4000000); os.write(2, b'y' * 4000000)",
                ],
                stdout_path=stdout,
                stderr_path=stderr,
                timeout=10,
                poll_interval=0.01,
                trusted_executable=sys.executable,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(stdout.stat().st_size, 4_000_000)
            self.assertEqual(stderr.stat().st_size, 4_000_000)
            self.assertLessEqual(len(result.stdout.encode()), 1 << 20)
            self.assertLessEqual(len(result.stderr.encode()), 1 << 20)


if __name__ == "__main__":
    unittest.main()
