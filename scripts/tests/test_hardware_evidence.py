from hashlib import sha256
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from promotion import EVIDENCE, beta_manifest, main, verify_promotion
from release_workflow import MANAGED, MANIFEST


class HardwareEvidenceTests(unittest.TestCase):
    def setUp(self):
        sha = "1" * 64
        self.beta = {
            "source_commit": "a" * 40,
            "profiles": [{"id": "gcc-kernel", "images": [
                {"radio": "dual-band", "file": "image.bin", "hardware_verification": "not-tested"},
            ]}],
            "assets": {"image.bin": {"sha256": sha}},
        }
        self.stable = json.loads(json.dumps(self.beta))
        self.stable["profiles"][0]["images"][0]["hardware_verification"] = "stability-tested"
        self.stable["assets"][EVIDENCE] = {}
        self.stable["promotion"] = {"beta_tag": "v1.2.0-beta.1", "stable_tag": "v1.2.0"}
        self.observation = {
            "compiler": "gcc-kernel", "radio": "dual-band", "image_sha256": sha,
            "started_at": "2020-01-01T00:00:00Z", "ended_at": "2020-01-04T00:00:00Z",
            "checks": dict.fromkeys(("boot", "reboot", "memory", "wifi", "network", "packages",
                                     "local_monitoring", "recovery"), "pass"),
            "configuration": "wired management", "workload": "fixture", "observations": "fixture",
        }
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def write_report(self):
        (self.directory / EVIDENCE).write_text(json.dumps({
            "source_commit": self.beta["source_commit"], "variants": [self.observation],
        }))

    def test_stable_may_update_only_hardware_status_and_evidence(self):
        self.write_report()
        verify_promotion(self.directory, self.stable, self.beta)

    def test_verified_beta_bytes_cannot_be_replaced_for_stable(self):
        self.write_report()
        self.stable["assets"]["image.bin"]["sha256"] = "3" * 64
        with self.assertRaisesRegex(ValueError, "must match Beta exactly"):
            verify_promotion(self.directory, self.stable, self.beta)

    def test_stable_rejects_a_short_observation_for_the_exact_image(self):
        self.observation["ended_at"] = "2020-01-03T23:59:59Z"
        self.write_report()
        with self.assertRaisesRegex(ValueError, "Incomplete hardware evidence"):
            verify_promotion(self.directory, self.stable, self.beta)

    def test_prepared_directory_requires_the_same_requested_beta_and_evidence(self):
        self.write_report()
        evidence = self.directory / EVIDENCE
        contents = evidence.read_bytes()
        self.stable["assets"][EVIDENCE] = {"size": len(contents), "sha256": sha256(contents).hexdigest()}
        args = ["promotion.py", "prepare", "--directory", str(self.directory), "--evidence", str(evidence),
                "--commit", self.stable["source_commit"], "--tag", "v1.2.0", "--beta"]
        with patch("promotion.verify_local", return_value=self.stable):
            with patch.object(sys, "argv", [*args, "v1.2.0-beta.1"]):
                self.assertEqual(main(), 0)
            with patch.object(sys, "argv", [*args, "v1.2.0-beta.2"]), patch("promotion.sys.stderr") as errors:
                self.assertEqual(main(), 1)
                self.assertIn("differs from the requested Beta", errors.write.call_args_list[0].args[0])

    def test_beta_manifest_rejects_published_payload_with_a_different_digest(self):
        self.beta["assets"]["image.bin"]["size"] = 10
        blob = json.dumps(self.beta).encode()
        tag = "v1.2.0-beta.1"
        commit = self.beta["source_commit"]
        release = {"id": 1, "target_commitish": commit, "tag_name": tag, "immutable": True,
                   "draft": False, "prerelease": True, "body": MANAGED,
                   "assets": [
                       {"name": MANIFEST, "id": 2, "state": "uploaded", "size": len(blob),
                        "digest": "sha256:" + sha256(blob).hexdigest()},
                       {"name": "image.bin", "id": 3, "state": "uploaded", "size": 10,
                        "digest": "sha256:" + "2" * 64},
                   ]}
        github = Mock()
        github.releases.return_value = [release]
        github.tag_commit.return_value = commit
        github.download.side_effect = lambda entry, directory, name: (directory / name).write_bytes(blob)
        with self.assertRaisesRegex(ValueError, "Published Beta assets differ"):
            beta_manifest(github, self.directory, tag, commit)
