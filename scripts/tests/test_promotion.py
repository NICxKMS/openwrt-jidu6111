import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "promotion.py"
sys.path.insert(0, str(SCRIPT.parent))
import promotion
COMMIT = "1" * 40
BUNDLE = "2" * 64
WORKER = "1a221c5f-c374-4436-a865-fe9fbe404042"
NEW_WORKER = "bfb778aa-6e7a-51a0-b651-2d816360899d"
TAG = "v1.0.1"
PACKAGE = "1.0.0-r7"


def stamp(delta=timedelta()):
    return (datetime.now(timezone.utc) + delta).isoformat()


class PromotionTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name)
        self.state = self.path / "state"
        self.manifest = self.path / "manifest.json"
        self.write_manifest("combined")

    def write_manifest(self, kind, **promotion):
        if kind in {"dashboard", "api", "combined"}:
            promotion["expected_worker_version"] = WORKER
        if kind == "combined":
            promotion["required_agent_version"] = PACKAGE
        self.manifest.write_text(json.dumps({
            "schema": 1, "source_commit": COMMIT,
            "assets": {"monitor-bundle.tar.gz": {"sha256": BUNDLE, "size": 2}},
            "profiles": [{
                "board": "jiorouter,ax6000-jidu6111", "kernel": "6.18.60-r1~abcd1",
                "architecture": "aarch64_cortex-a53", "firmware_revision": "r0+38470-c3af7ee2f2",
                "key_sha256": "4" * 64,
            }],
            "promotion": {"kind": kind, **promotion},
        }))

    def command(self, command, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--state-dir", str(self.state), command, *map(str, args)],
            capture_output=True, text=True,
        )
        if ok and result.returncode:
            self.fail(result.stderr)
        if not ok:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def pending(self, command, *args, **kwargs):
        return self.command(command, "--manifest", self.manifest, "--reservation-tag", TAG, *args, **kwargs)

    def evidence(self):
        return ["--version", PACKAGE, "--installed-at", stamp(),
                "--received-at", stamp()]

    def test_combined_requires_exact_fresh_agent_evidence(self):
        self.pending("prepare")
        self.assertIn("telemetry evidence", self.pending("deployment-inputs", ok=False).stderr)
        evidence = self.evidence()
        evidence[1] = "1.0.0-r6"
        self.command("record-agent", *evidence, ok=False)
        evidence = self.evidence()
        evidence[-1] = stamp(timedelta(minutes=-10))
        self.command("record-agent", *evidence, ok=False)
        self.command("record-agent", *self.evidence())
        inputs = json.loads(self.pending("deployment-inputs").stdout)
        self.assertEqual(inputs["candidate"], COMMIT)
        self.assertEqual(inputs["manifest_sha"], hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        self.assertEqual(inputs["agent_version"], PACKAGE)
        self.assertEqual(inputs["bundle_sha"], BUNDLE)

    def test_changed_manifest_and_parallel_promotions_are_rejected(self):
        self.pending("prepare")
        self.assertIn("already reserved", self.pending("prepare", ok=False).stderr)
        self.write_manifest("api")
        self.assertIn("match", self.pending("deployment-inputs", ok=False).stderr)

    def test_completion_keeps_only_observed_production_state(self):
        self.write_manifest("bootstrap")
        self.pending("prepare")
        self.pending("authorize-publication", ok=False)
        observed = self.path / "observed.json"
        observed.write_text(json.dumps({
            "router": {"board": "jiorouter,ax6000-jidu6111", "kernel": "6.18.60-r1~abcd1",
                       "firmware": "wrong", "agent_version": PACKAGE,
                       "architecture": "aarch64_cortex-a53", "trusted_keys": ["4" * 64]},
            "worker_version": WORKER, "migrations": ["001"], "verified_at": stamp(),
            "checks": ["router_identity", "feed_signature", "worker_health", "database_state", "recovery_ready"],
        }))
        self.assertIn("match a release profile", self.pending("verify-production", "--observed", observed, ok=False).stderr)
        observed.write_text(observed.read_text().replace("wrong", "r0+38470-c3af7ee2f2"))
        self.pending("verify-production", "--observed", observed)
        self.pending("authorize-publication")
        evidence = json.loads(self.pending("publication-evidence").stdout)
        self.assertEqual(evidence["candidate"], COMMIT)
        self.assertEqual(evidence["worker_version"], WORKER)
        self.assertNotIn("router", evidence)
        self.assertNotIn("migrations", evidence)
        self.command("verify-publication-evidence", "--manifest", self.manifest,
                     "--reservation-tag", TAG, "--evidence", json.dumps(evidence))
        evidence["required_checks"].remove("database_state")
        self.command("verify-publication-evidence", "--manifest", self.manifest,
                     "--reservation-tag", TAG, "--evidence", json.dumps(evidence), ok=False)
        github = Mock()
        github.api.return_value = {
            "tag_name": TAG, "body": "<!-- jidu6111-managed -->\n<!-- jidu6111-publication-pending -->",
            "draft": False, "prerelease": False, "immutable": True, "target_commitish": COMMIT,
        }
        github.tag_commit.return_value = COMMIT
        options = SimpleNamespace(command="complete", manifest=self.manifest, reservation_tag=TAG,
                                  state_dir=self.state, repo=promotion.REPO)
        with patch.object(promotion, "GitHub", return_value=github), \
             patch.object(promotion, "released_manifest_bytes") as remote:
            with self.assertRaisesRegex(ValueError, "Latest"):
                promotion.local_command(options)
            self.assertIsNone(json.loads(self.command("status").stdout)["production"])
            github.api.return_value["body"] = "<!-- jidu6111-managed -->"
            remote.return_value = b"wrong bytes"
            with self.assertRaisesRegex(ValueError, "checksum"):
                promotion.local_command(options)
            remote.return_value = self.manifest.read_bytes()
            promotion.local_command(options)
        state = json.loads(self.command("status").stdout)
        self.assertEqual(state["production"]["release_tag"], TAG)
        self.assertIsNone(state["pending"])
        self.assertEqual((self.state / "state.json").stat().st_mode & 0o777, 0o600)

    def test_production_run_must_approve_and_activate_exact_version(self):
        manifest = json.loads(self.manifest.read_text())
        digest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        evidence = {"production_run_id": 57, "worker_version": NEW_WORKER}
        receipt = {"candidate": COMMIT, "release_tag": TAG, "manifest_sha": digest,
                   "bundle_sha": BUNDLE, "worker_version": NEW_WORKER}
        documents = {
            "actions/runs/57": {
                "status": "completed", "conclusion": "success", "event": "workflow_dispatch",
                "head_sha": COMMIT, "head_branch": "stable", "head_repository": {"full_name": "user/repo"},
                "path": ".github/workflows/production.yml", "run_attempt": 2,
            },
            "actions/runs/57/approvals": [
                {"state": "approved", "user": {"login": "owner"}, "environments": [{"name": "production"}]},
            ],
            "actions/runs/57/attempts/2/jobs?per_page=100": {"jobs": [
                {"name": "deploy", "conclusion": "success",
                 "check_run_url": "https://api.github.com/repos/user/repo/check-runs/123"},
            ]},
            "check-runs/123/annotations?per_page=100&page=1": [
                {"title": "JIDU6111 production receipt", "annotation_level": "notice",
                 "message": json.dumps(receipt)},
            ],
        }
        github = Mock()
        github.repo = "user/repo"
        github.api.side_effect = documents.__getitem__
        promotion.verify_production_run(github, manifest, digest, TAG, evidence, "owner")
        evidence["worker_version"] = WORKER
        with self.assertRaisesRegex(ValueError, "activated"):
            promotion.verify_production_run(github, manifest, digest, TAG, evidence, "owner")
        evidence["worker_version"] = NEW_WORKER
        documents["actions/runs/57"]["head_sha"] = "5" * 40
        with self.assertRaisesRegex(ValueError, "exact Stable"):
            promotion.verify_production_run(github, manifest, digest, TAG, evidence, "owner")

    def test_deployment_gate_rejects_clobbered_bundle_and_stale_evidence(self):
        options = ["--manifest", self.manifest, "--candidate", COMMIT, "--bundle-sha", BUNDLE,
                   "--manifest-sha", hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
                   "--agent-version", PACKAGE, "--agent-installed-at", stamp(timedelta(minutes=-3)),
                   "--telemetry-received-at", stamp(timedelta(minutes=-2))]
        self.command("verify-deployment", *options)
        options[5] = "3" * 64
        self.command("verify-deployment", *options, ok=False)
        options[5] = BUNDLE
        options[-1] = stamp(timedelta(days=-2))
        self.command("verify-deployment", *options, ok=False)


if __name__ == "__main__":
    unittest.main()
