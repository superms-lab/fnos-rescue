import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path


HELPERS = Path("helpers").resolve()


def load_builder():
    sys.path.insert(0, str(HELPERS))
    try:
        spec = importlib.util.spec_from_file_location(
            "build_synthetic_chunk_tree_cache_test", HELPERS / "build_synthetic_chunk_tree.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(HELPERS))


def cache_bytes(*, count: int = 1, stripes: int = 1, trailing: bytes = b"") -> bytes:
    record = bytearray(88)
    struct.pack_into("=IHH", record, 0, 1, stripes, 1)
    struct.pack_into("=QQ", record, 8, 1, 256)
    record[24] = 228
    struct.pack_into("=QQQQQ", record, 32, 0, 2, 4096, 1, 4096)
    struct.pack_into("=III", record, 72, 4096, 4096, 4096)
    stripe = struct.pack("=QQ16s", 1, 65536, b"1" * 16)
    return struct.pack("=8sII", b"BTRCHNK1", 1, count) + bytes(record) + stripe * stripes + trailing


class ChunkCacheValidationTests(unittest.TestCase):
    def test_accepts_exact_bounded_cache(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cache"
            path.write_bytes(cache_bytes())
            chunks = builder.read_cache(str(path))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["num_stripes"], 1)

    def test_rejects_oversized_counts_and_trailing_data(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            too_many = root / "too-many"
            too_many.write_bytes(struct.pack("=8sII", b"BTRCHNK1", 1, 1_048_577))
            with self.assertRaisesRegex(RuntimeError, "record count"):
                builder.read_cache(str(too_many))
            trailing = root / "trailing"
            trailing.write_bytes(cache_bytes(trailing=b"evil"))
            with self.assertRaisesRegex(RuntimeError, "trailing"):
                builder.read_cache(str(trailing))

    def test_rejects_zero_or_unbounded_stripes(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cache"
            path.write_bytes(cache_bytes(stripes=0))
            with self.assertRaisesRegex(RuntimeError, "stripe count"):
                builder.read_cache(str(path))


if __name__ == "__main__":
    unittest.main()
