import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import release_workflow as release


class FirmwareChannelTests(unittest.TestCase):
    def test_only_numeric_beta_tags_are_candidates(self):
        def entry(tag):
            return {"tag_name": tag, "prerelease": True, "body": release.MANAGED}

        self.assertEqual(release.channel_of(entry("v1.4.0-beta.10")), "beta")
        self.assertIsNone(release.channel_of(entry("v1.4.0-dev.2.1")))

    def test_stable_maintenance_release_preserves_newer_latest(self):
        latest = {"tag_name": "v1.10.0", "draft": False, "prerelease": False,
                  "immutable": True, "body": release.MANAGED}
        self.assertFalse(release.should_mark_latest([latest], "stable", "v1.9.99"))
        self.assertTrue(release.should_mark_latest([latest], "stable", "v1.11.0"))
