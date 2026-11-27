import fcntl
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_storage import build_root, cleanup


class ScratchCleanupTests(unittest.TestCase):
    def test_configured_build_root_resolves_symlinks_like_builder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual = root / "actual"
            actual.mkdir()
            link = root / "link"
            link.symlink_to(actual, target_is_directory=True)
            with patch.dict(os.environ, {"JIDU6111_BUILD_ROOT": str(link)}):
                self.assertEqual(build_root(), actual.resolve())

    def test_only_removes_owned_unlocked_builds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "build.acd12345"
            abandoned = root / "build.12345a_d"
            unrelated = root / "build.aaaaaaaa"
            for path in (active, abandoned, unrelated):
                path.mkdir()
            for path in (active, abandoned):
                (path / ".jidu6111-owned").touch()
            trap = root / "build.bbbbbbbb"
            trap.symlink_to(unrelated, target_is_directory=True)
            fd = os.open(active, os.O_RDONLY | os.O_DIRECTORY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(cleanup(root, apply=False), [abandoned])
                self.assertTrue(abandoned.exists())
                self.assertEqual(cleanup(root, apply=True), [abandoned])
                self.assertTrue(active.exists())
                self.assertTrue(unrelated.exists())
                self.assertTrue(trap.is_symlink())
                self.assertFalse(abandoned.exists())
            finally:
                os.close(fd)
