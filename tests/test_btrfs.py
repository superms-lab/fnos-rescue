import unittest

from fnos_rescue.plugins.fnos_btrfs import parse_dump_super


class ParseDumpSuperTests(unittest.TestCase):
    def test_parses_valid_third_mirror(self) -> None:
        text = """
        csum            0x12345678 [match]
        magic           _BHRfS_M [match]
        fsid            11111111-2222-3333-4444-555555555555
        generation      42
        root            987654321
        chunk_root      0
        """
        parsed = parse_dump_super(text)
        self.assertTrue(parsed["valid_magic"])
        self.assertTrue(parsed["valid_checksum"])
        self.assertEqual(parsed["generation"], "42")
        self.assertEqual(parsed["root"], "987654321")

    def test_rejects_blank_super(self) -> None:
        parsed = parse_dump_super("magic ........................")
        self.assertFalse(parsed["valid_magic"])
        self.assertFalse(parsed["valid_checksum"])


if __name__ == "__main__":
    unittest.main()
