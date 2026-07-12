import tempfile
import unittest
from pathlib import Path

from fnos_rescue.verify import sha256_file, verify_samples


class VerifyTests(unittest.TestCase):
    def test_hashes_and_skips_empty_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "empty.bin").write_bytes(b"")
            (root / "hello.txt").write_text("hello")
            self.assertEqual(
                sha256_file(root / "hello.txt"),
                "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            )
            samples = verify_samples(root, 10)
            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0]["size"], 5)


if __name__ == "__main__":
    unittest.main()
