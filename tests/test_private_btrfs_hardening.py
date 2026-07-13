import unittest
from pathlib import Path


SOURCE = Path("vendor/btrfs-progs-v7/rescue-chunk-recover.c")


class PrivateBtrfsHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text()

    def test_forced_roots_require_complete_tree_evidence(self) -> None:
        for marker in (
            '"BTRFS_FORCE_FS_ROOT"',
            '"BTRFS_FORCE_EXTRACT_ROOT"',
            '"%s_FSID"',
            '"OWNER"',
            '"GENERATION"',
            '"LEVEL"',
            "btrfs_header_bytenr(eb)",
            "btrfs_header_owner(eb)",
            "btrfs_header_generation(eb)",
            "btrfs_header_level(eb)",
        ):
            self.assertIn(marker, self.source)

    def test_salvage_opens_devices_read_only(self) -> None:
        self.assertIn("salvage_readonly ? O_RDONLY : O_RDWR", self.source)
        self.assertIn("forced historical roots are allowed only for read-only salvage", self.source)

    def test_cache_parser_has_bounds_and_exact_length_check(self) -> None:
        self.assertIn("CHUNK_CACHE_MAX_RECORDS", self.source)
        self.assertIn("CHUNK_CACHE_MAX_STRIPES", self.source)
        self.assertIn("remaining != 0", self.source)
        self.assertIn("in.sub_stripes > in.num_stripes", self.source)

    def test_inventory_paths_are_relative_and_binary_safe(self) -> None:
        self.assertIn("base64_path(child)", self.source)
        self.assertIn("path_b64\\n", self.source)
        self.assertIn('!prefix[0] && asprintf(&child, "%s", name)', self.source)
        self.assertIn("fflush(out) || fsync(fileno(out))", self.source)
        self.assertIn("fsync(fd)", self.source)
        self.assertIn("cached_inode_size(root, location.objectid, &entry_size)", self.source)
        self.assertIn("ret = -ENOENT", self.source)


if __name__ == "__main__":
    unittest.main()
