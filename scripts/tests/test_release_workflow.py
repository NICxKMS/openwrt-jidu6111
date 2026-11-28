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


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.github = Mock()
        self.tag = "v1.1.0-beta.2"
        self.draft = {
            "tag_name": self.tag, "id": 2, "target_commitish": COMMIT,
            "draft": True, "prerelease": True,
            "assets": [{"name": release.MANIFEST, "state": "uploaded", "size": 123,
                        "digest": "sha256:" + "b" * 64, "id": 47}],
            "body": f"{release.MANAGED}\n{release.PENDING}",
        }
        self.old = {**self.draft, "id": 1, "tag_name": "v1.1.0-beta.1", "draft": False,
                    "body": release.MANAGED, "immutable": True}
        self.receipt = release.asset_receipt(self.draft)
        self.github.releases.return_value = [self.draft, self.old]
        self.github.tag_commit.return_value = COMMIT
        self.github.patch.return_value = {**self.draft, "draft": False, "immutable": True}

    def test_asset_replaced_after_verification_blocks_publication(self):
        self.draft["assets"][0]["id"] = 51
        with self.assertRaisesRegex(ValueError, "changed after"):
            release.publish(self.github, "beta", self.tag, COMMIT, self.receipt)
        self.github.patch.assert_not_called()

    def test_keeps_previous_and_delays_eligibility_until_public_download(self):
        self.github.verify_public.side_effect = ValueError("download failed")
        with self.assertRaisesRegex(ValueError, "download failed"):
            release.publish(self.github, "beta", self.tag, COMMIT, self.receipt)
        self.github.patch.assert_called_once_with(self.draft, draft=False, make_latest="false")
        self.github.delete.assert_not_called()

    def test_success_makes_new_beta_eligible_and_preserves_previous(self):
        release.publish(self.github, "beta", self.tag, COMMIT, self.receipt)
        self.github.patch.assert_called_with(self.github.patch.return_value, body=release.MANAGED, make_latest="false")
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
