import sys
import unittest

from fnos_rescue.errors import JobControlRequested
from fnos_rescue.runner import run_interruptible


class InterruptibleRunnerTests(unittest.TestCase):
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
            )
        self.assertEqual(raised.exception.action, "pause")


if __name__ == "__main__":
    unittest.main()
