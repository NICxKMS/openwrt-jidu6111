"""Regression checks for package feed selection and unpacking."""

import hashlib
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from release_workflow import PENDING
from release_feed import RouterIdentity, SelectedFeed, download_feed, extract_feed, releases_by_version, select_feed


BOARD = "jiorouter,ax6000-jidu6111"
KEY = "a" * 64
KERNEL = "6.18.60~matching-r1"
ARCH = "aarch64_cortex-a53"
MANIFEST = "release-manifest.json"
STABLE = "v1.0.0"
BETA = "v1.0.1-beta.4"


def release(tag, *, prerelease=False, managed=True):
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": prerelease, "immutable": True,
        "published_at": "2026-11-27T00:00:00Z",
        "body": "<!-- jidu6111-managed -->" if managed else "",
        "assets": [{"name": MANIFEST}, {"name": "feed.tar.gz"}],
    }


def manifest(**profile_changes):
    return {
        "schema": 1,
        "source_commit": "b" * 40,
        "profiles": [{
            "id": "gcc-kernel",
            "board": BOARD,
            "architecture": ARCH,
            "kernel": KERNEL,
            "key_sha256": KEY,
            "feed": "feed.tar.gz",
            "images": [],
        } | profile_changes],
        "assets": {"feed.tar.gz": {"sha256": "c" * 64, "size": 10}},
    }


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.router = RouterIdentity(BOARD, ARCH, KERNEL, frozenset({KEY}))

    @patch("release_feed.read_json")
    def test_beta_skips_pending_and_unmanaged_releases(self, read):
        newest = release("v1.0.1-beta.5", prerelease=True)
        newest["published_at"] = "2026-11-27T01:00:00Z"
        newest["body"] += "\n" + PENDING
        unmanaged = release("v1.0.1-beta.6", prerelease=True, managed=False)
        read.return_value = [newest, unmanaged, release("v1.0.1-beta.3", prerelease=True), release(BETA, prerelease=True)]
        self.assertEqual([entry["tag_name"] for entry in releases_by_version()], [BETA, "v1.0.1-beta.3"])

    @patch("release_feed.release_manifest")
    @patch("release_feed.releases_by_version")
    def test_auto_prefers_stable_and_does_not_fetch_beta_manifest(self, channel, read):
        channel.return_value = [release(BETA, prerelease=True), release(STABLE)]
        read.return_value = manifest()
        result = select_feed(self.router)
        self.assertEqual((result.channel, result.tag, result.profile), ("stable", STABLE, "gcc-kernel"))
        self.assertEqual(channel.call_count, 1)
        self.assertEqual(read.call_count, 1)

    @patch("release_feed.release_manifest")
    @patch("release_feed.releases_by_version")
    def test_auto_uses_beta_only_when_stable_does_not_match(self, channel, read):
        channel.return_value = [release(BETA, prerelease=True), release(STABLE)]
        read.side_effect = [manifest(kernel="6.18.60~different-r1"), manifest()]
        result = select_feed(self.router)
        self.assertEqual(result.channel, "beta")

    @patch("release_feed.release_manifest")
    @patch("release_feed.releases_by_version")
    def test_auto_uses_older_matching_stable_before_beta(self, channel, read):
        channel.return_value = [release("v2.0.0"), release(BETA, prerelease=True), release(STABLE)]
        read.side_effect = [manifest(kernel="6.18.60~different-r1"), manifest()]
        self.assertEqual(select_feed(self.router).tag, STABLE)
        self.assertEqual([call.args[0]["tag_name"] for call in read.call_args_list], ["v2.0.0", STABLE])

    @patch("release_feed.release_manifest")
    @patch("release_feed.releases_by_version")
    def test_requires_every_router_compatibility_field(self, channel, read):
        channel.return_value = [release(STABLE)]
        for changed in (
            {"board": "other"}, {"architecture": "aarch64_generic"},
            {"key_sha256": "e" * 64}, {"kernel": "6.18.60~wrong-r1"},
        ):
            with self.subTest(changed=changed):
                read.return_value = manifest(**changed)
                with self.assertRaisesRegex(RuntimeError, "No compatible"):
                    select_feed(self.router, "stable")

    @patch("release_feed.release_manifest")
    @patch("release_feed.releases_by_version")
    def test_unverified_or_missing_asset_cannot_be_selected(self, channel, read):
        channel.return_value = [release(STABLE)]
        read.return_value = manifest(feed="missing.tar.gz")
        with self.assertRaisesRegex(RuntimeError, "asset"):
            select_feed(self.router, "stable")


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.archive = self.root / "feed.tar.gz"

    def write_archive(self, entries):
        with tarfile.open(self.archive, "w:gz") as output:
            for name, body, kind in entries:
                entry = tarfile.TarInfo(name)
                entry.type = kind
                if kind == tarfile.SYMTYPE:
                    entry.linkname = "/etc/passwd"
                entry.size = len(body)
                output.addfile(entry, io.BytesIO(body))

    def test_unpack_only_signed_feed_files(self):
        self.write_archive([
            ("./packages.adb", b"index", tarfile.REGTYPE),
            ("htop-1.0-r1.apk", b"package", tarfile.REGTYPE),
        ])
        feed = self.root / "verified"
        extract_feed(self.archive, feed)
        self.assertEqual(sorted(item.name for item in feed.iterdir()), ["htop-1.0-r1.apk", "packages.adb"])

    def test_rejects_traversal_links_and_duplicate_names(self):
        for index, entries in enumerate((
            [("../escape.apk", b"bad", tarfile.REGTYPE)],
            [("link.apk", b"", tarfile.SYMTYPE)],
            [("packages.adb", b"one", tarfile.REGTYPE), ("./packages.adb", b"two", tarfile.REGTYPE)],
        )):
            with self.subTest(entries=entries):
                self.write_archive(entries)
                with self.assertRaises(RuntimeError):
                    extract_feed(self.archive, self.root / f"attempt-{index}")

    @patch("release_feed.urlopen")
    def test_download_pins_release_and_removes_the_archive_after_verification(self, request):
        self.write_archive([
            ("packages.adb", b"index", tarfile.REGTYPE),
            ("htop-1.0-r1.apk", b"package", tarfile.REGTYPE),
        ])
        blob = self.archive.read_bytes()
        self.archive.unlink()
        request.return_value = io.BytesIO(blob)
        selection = SelectedFeed(
            "stable", STABLE, "gcc-kernel", "feed.tar.gz", len(blob), hashlib.sha256(blob).hexdigest()
        )
        feed = download_feed(selection, self.root)
        self.assertIn("/releases/download/v1.0.0/feed.tar.gz", request.call_args.args[0].full_url)
        self.assertFalse(self.archive.exists())
        self.assertEqual((feed / "packages.adb").read_bytes(), b"index")

    @patch("release_feed.urlopen")
    def test_download_rejects_same_size_with_wrong_hash(self, request):
        request.return_value = io.BytesIO(b"wrong")
        selection = SelectedFeed("stable", STABLE, "gcc-kernel", "feed.tar.gz", 5, hashlib.sha256(b"right").hexdigest())
        with self.assertRaisesRegex(RuntimeError, "checksum"):
            download_feed(selection, self.root)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
