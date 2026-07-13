import tempfile
import unittest
import hashlib
import zipfile
from pathlib import Path

from fnos_rescue.verify import sha256_file, verify_file, verify_samples


class VerifyTests(unittest.TestCase):
    def test_hashes_and_classifies_empty_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "empty.bin").write_bytes(b"")
            (root / "hello.txt").write_text("hello")
            self.assertEqual(
                sha256_file(root / "hello.txt"),
                "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            )
            samples = verify_samples(root, 10)
            self.assertEqual(len(samples), 2)
            by_name = {Path(item["path"]).name: item for item in samples}
            self.assertEqual(by_name["hello.txt"]["size"], 5)
            self.assertEqual(by_name["empty.bin"]["classification"], "unvalidated")

    def test_structural_validation_and_trusted_empty_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "valid.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("hello.txt", "hello")
            self.assertEqual(verify_file(archive).classification, "validated")
            broken = root / "broken.zip"
            broken.write_bytes(archive.read_bytes()[:-4])
            self.assertEqual(verify_file(broken).classification, "invalid")
            empty = root / "empty.bin"
            empty.write_bytes(b"")
            result = verify_file(empty, expected_size=0, expected_empty=True)
            self.assertEqual(result.classification, "genuine_empty")
            known = root / "known.bin"
            known.write_bytes(b"opaque")
            digest = hashlib.sha256(b"opaque").hexdigest()
            self.assertEqual(verify_file(known, expected_sha256=digest).classification, "validated")


if __name__ == "__main__":
    unittest.main()
