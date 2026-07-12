import importlib.util
import tempfile
import unittest
from pathlib import Path


def load_helper():
    path = Path("helpers/copy_validated_paths.py")
    spec = importlib.util.spec_from_file_location("copy_validated_paths", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def load_historical_helper():
    path = Path("helpers/try_historical_subvolume_roots.py")
    spec = importlib.util.spec_from_file_location("try_historical_subvolume_roots", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class CopyHelperSafetyTests(unittest.TestCase):
    def test_rejects_traversal_and_symlink(self) -> None:
        helper = load_helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            outside = root / "outside"
            outside.write_text("secret")
            (source / "link").symlink_to(outside)
            with self.assertRaises(ValueError):
                helper.safe_path(str(source), "../outside")
            with self.assertRaises(ValueError):
                helper.safe_path(str(source), "link")

    def test_historical_copy_rejects_destination_escape(self) -> None:
        helper = load_historical_helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                helper.safe_destination(str(root), "../../outside")


if __name__ == "__main__":
    unittest.main()
