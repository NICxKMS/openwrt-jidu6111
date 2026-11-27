import hashlib
import json
import pathlib
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import release_workflow as release


COMMIT = "a" * 40


def entry(tag, *, draft=False, pending=False, prerelease=True, release_id=1):
    return {
        "tag_name": tag, "id": release_id, "target_commitish": COMMIT,
        "draft": draft, "prerelease": prerelease, "assets": [],
        "body": release.MANAGED + (f"\n{release.PENDING}" if pending else ""),
    }


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.github = Mock()
        self.github.branch_head.return_value = COMMIT
        self.github.tag_commit.return_value = COMMIT
        self.old = entry("v1.1.0-dev.1.1")
        self.new = entry("v1.1.0-dev.2.1", draft=True, pending=True, release_id=2)
        self.github.releases.return_value = [self.new, self.old]

    def test_keeps_previous_when_upload_is_invalid(self):
        self.github.verify_draft.side_effect = ValueError("bad checksum")
        with self.assertRaisesRegex(ValueError, "bad checksum"):
            release.publish(self.github, "development", self.new["tag_name"], COMMIT)
        self.github.patch.assert_not_called()
        self.github.delete.assert_not_called()

    def test_retires_only_after_public_checks(self):
        self.github.patch.side_effect = [
            {**self.new, "draft": False, "immutable": True},
            {**self.new, "draft": False, "immutable": True, "body": release.MANAGED},
        ]
        release.publish(self.github, "development", self.new["tag_name"], COMMIT)
        calls = [call[0] for call in self.github.mock_calls]
        self.assertLess(calls.index("verify_public"), calls.index("delete"))
        self.github.delete.assert_called_once_with(self.old)

    def test_keeps_previous_if_public_download_fails(self):
        self.github.patch.return_value = {**self.new, "draft": False, "immutable": True}
        self.github.verify_public.side_effect = ValueError("download failed")
        with self.assertRaisesRegex(ValueError, "download failed"):
            release.publish(self.github, "development", self.new["tag_name"], COMMIT)
        self.github.delete.assert_not_called()

    def test_blocks_a_stale_commit_and_an_active_stable_promotion(self):
        self.github.branch_head.return_value = "b" * 40
        with self.assertRaisesRegex(ValueError, "head"):
            release.publish(self.github, "development", self.new["tag_name"], COMMIT)
        self.github.branch_head.return_value = COMMIT
        reservation = entry("v1.1.0", draft=True, pending=True, prerelease=False)
        self.github.releases.return_value = [self.new, reservation, self.old]
        with self.assertRaisesRegex(ValueError, "promotion"):
            release.publish(self.github, "development", self.new["tag_name"], COMMIT)
        self.github.patch.assert_not_called()

    def test_retains_previous_until_native_discovery_is_ready(self):
        self.github.patch.side_effect = [
            {**self.new, "draft": False, "immutable": True},
            {**self.new, "draft": False, "immutable": True, "body": release.MANAGED},
        ]
        self.github.verify_discovery.side_effect = ValueError("native discovery is stale")
        with self.assertRaisesRegex(ValueError, "discovery"):
            release.publish(self.github, "development", self.new["tag_name"], COMMIT)
        self.github.delete.assert_not_called()

    def test_consumption_rejects_extra_firmware_and_feeds(self):
        firmware = {"original.bin": {"sha256": "a" * 64}, "feed.tar.gz": {"sha256": "b" * 64}}
        self.github.verify_draft.return_value = firmware
        with self.assertRaisesRegex(ValueError, "match Stable"):
            release.verify_consumed_development(self.github, self.old, {**firmware, "other.bin": {}})

    def test_same_commit_retry_cannot_replace_a_newer_verified_candidate(self):
        newer = entry("v1.1.0-dev.3.1", release_id=3)
        self.github.releases.return_value = [newer, self.new, self.old]
        with self.assertRaisesRegex(ValueError, "newer"):
            release.publish(self.github, "development", self.new["tag_name"], COMMIT)
        self.github.patch.assert_not_called()
        self.github.delete.assert_not_called()


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = pathlib.Path(self.temporary.name)
        (self.directory / "image.bin").write_bytes(b"image")
        self.index = self.directory / "packages.adb"
        self.index.write_bytes(b"index")
        self.apk = self.directory / "kernel-6.18.60~1234abcd-r1.apk"
        self.apk.write_bytes(b"kernel")
        with tarfile.open(self.directory / "feed.tar.gz", "w:gz") as archive:
            archive.add(self.index, arcname=self.index.name)
            archive.add(self.apk, arcname=self.apk.name)
        self.index.unlink()
        self.apk.unlink()
        self.manifest = {
            "schema": 1, "source_commit": COMMIT,
            "profiles": [{
                "id": "legacy", "board": "jiorouter,ax6000-jidu6111",
                "architecture": "aarch64_cortex-a53", "kernel": "6.18.60~abi-r1",
                "key_sha256": "f" * 64, "feed": "feed.tar.gz",
                "images": [{"radio": "dual-band", "file": "image.bin"}],
            }],
            "assets": {
                path.name: {"size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in self.directory.iterdir()
            },
        }

    def test_requires_an_exact_set_of_checksummed_files(self):
        path = self.directory / "release-manifest.json"
        path.write_text(json.dumps(self.manifest))
        self.assertEqual(release.verify_local(self.directory, COMMIT), self.manifest)
        (self.directory / "image.bin").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            release.verify_local(self.directory, COMMIT)

    def test_rejects_an_undeclared_staging_file(self):
        (self.directory / "release-manifest.json").write_text(json.dumps(self.manifest))
        (self.directory / "extra.txt").write_text("not an asset")
        with self.assertRaisesRegex(ValueError, "only manifest assets"):
            release.verify_local(self.directory, COMMIT)

    def test_invalid_schema_and_kernel_are_rejected_before_staging(self):
        path = self.directory / "release-manifest.json"
        for field, value in (("schema", True), ("kernel", None)):
            with self.subTest(field=field):
                invalid = json.loads(json.dumps(self.manifest))
                destination = invalid if field == "schema" else invalid["profiles"][0]
                destination[field] = value
                path.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    release.verify_local(self.directory, COMMIT)


class GitHubTests(unittest.TestCase):
    def test_reads_concatenated_paginated_json_from_older_gh(self):
        self.assertEqual(release.json_pages('  [{"id":1}] [{"id":2}]\n'), [[{"id": 1}], [{"id": 2}]])
