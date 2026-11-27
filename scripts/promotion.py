#!/usr/bin/env python3
"""Record an approved candidate and validate production evidence before publication."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request

from release_feed import METADATA_LIMIT, urlopen
from release_workflow import MANIFEST, REPO, GitHub, channel_of, is_pending

BUNDLE = "monitor-bundle.tar.gz"
RECEIPT_TITLE = "JIDU6111 production receipt"
KINDS = ("bootstrap", "dashboard", "api", "package", "combined", "database", "firmware")
CLOUD = {"dashboard", "api", "combined"}
BASE_CHECKS = {"router_identity", "feed_signature", "worker_health", "database_state", "recovery_ready"}
EXTRA_CHECKS = {
    "dashboard": {"dashboard_smoke", "telemetry"},
    "api": {"telemetry"},
    "package": {"telemetry"},
    "combined": {"dashboard_smoke", "telemetry"},
    "database": {"data_integrity", "telemetry"},
    "firmware": {"boot", "network", "radios", "package_install", "telemetry", "monitoring_history"},
}


def token(value, pattern, label):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"Invalid {label}")
    return value


def worker_version(value):
    return token(value, r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", "Worker version")


def timestamp(value):
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ValueError
        return when.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Expected a timestamp with an explicit UTC offset") from error


def now():
    return datetime.now(timezone.utc)


def deploys_worker(promotion):
    return promotion["kind"] in CLOUD or promotion.get("deploy_worker") is True


def read_manifest(path):
    data = path.read_bytes()
    manifest = json.loads(data)
    if manifest.get("schema") != 1:
        raise ValueError("Expected a version 1 release manifest")
    token(manifest.get("source_commit"), r"[a-f0-9]{40}", "release source commit")
    promotion = manifest["promotion"]
    if promotion.get("kind") not in KINDS:
        raise ValueError("Expected a documented promotion kind")
    agent = promotion.get("required_agent_version")
    if promotion["kind"] in {"combined", "package"} or agent:
        token(agent, r"[A-Za-z0-9][A-Za-z0-9._+~:-]{0,79}", "required agent package version")
    if deploys_worker(promotion):
        worker_version(promotion.get("expected_worker_version"))
        token(manifest["assets"][BUNDLE]["sha256"], r"[a-f0-9]{64}", "verified bundle checksum")
    return manifest, hashlib.sha256(data).hexdigest()


def check_evidence(expected, version=None, installed_at=None, received_at=None, *, earliest=None):
    if not expected:
        return
    if version != expected or not installed_at or not received_at:
        raise ValueError("Matching installed package and accepted telemetry evidence required")
    installed, received = timestamp(installed_at), timestamp(received_at)
    if (earliest and installed < earliest) or received < installed or received > now() + timedelta(minutes=2):
        raise ValueError("Telemetry must be accepted after the matching package was verified")
    if received < now() - timedelta(hours=24):
        raise ValueError("The telemetry evidence is stale. Record a fresh accepted sample")


def required_checks(kind):
    return BASE_CHECKS | EXTRA_CHECKS.get(kind, set())


def check_production(manifest, pending, observed):
    promotion = manifest["promotion"]
    kind = promotion["kind"]
    checks = observed.get("checks")
    if not isinstance(checks, list) or not all(isinstance(check, str) for check in checks):
        raise ValueError("Expected production check labels as a list of strings")
    missing = required_checks(kind) - set(checks)
    if missing:
        raise ValueError(f"Missing production checks: {', '.join(sorted(missing))}")
    when = timestamp(observed.get("verified_at"))
    if not timestamp(pending["prepared_at"]) <= when <= now() + timedelta(minutes=2):
        raise ValueError("Production verification must be newer than promotion preparation")
    worker_version(observed.get("worker_version"))
    # An approved bundle deploy changes the version. Other operations keep it pinned when specified.
    expected_worker = promotion.get("expected_worker_version")
    if deploys_worker(promotion):
        if observed["worker_version"] == expected_worker:
            raise ValueError("The approved Worker bundle has no observed deployment version")
        production_run_id(observed.get("production_run_id"))
    if not deploys_worker(promotion) and expected_worker and observed["worker_version"] != expected_worker:
        raise ValueError("Production Worker drifted from the approved baseline")
    router = observed["router"]
    trusted_keys = router.get("trusted_keys")
    if not isinstance(trusted_keys, list) or not all(
        isinstance(key, str) and re.fullmatch(r"[a-f0-9]{64}", key) for key in trusted_keys
    ):
        raise ValueError("Expected router signing fingerprints as a list of SHA-256 strings")
    if not any(
        profile["board"] == router.get("board")
        and profile["kernel"] == router.get("kernel")
        and profile["architecture"] == router.get("architecture")
        and profile["firmware_revision"] == router.get("firmware")
        and profile["key_sha256"] in trusted_keys
        for profile in manifest["profiles"]
    ):
        raise ValueError("The observed router identity and signing trust do not match a release profile")
    if not router.get("firmware") or not router.get("agent_version"):
        raise ValueError("Observed firmware and installed monitoring package are required")
    if not isinstance(observed.get("migrations"), list):
        raise ValueError("Expected the observed Supabase migration identifiers")
    expected_migrations = promotion.get("expected_migrations")
    if kind == "database" and not expected_migrations:
        raise ValueError("Database promotion requires expected hosted migration identifiers")
    if expected_migrations is not None and observed["migrations"] != expected_migrations:
        raise ValueError("Observed database state differs from the approved migration identifiers")
    expected_agent = promotion.get("required_agent_version")
    if expected_agent:
        if router.get("agent_version") != expected_agent:
            raise ValueError("Observed router agent differs from the required version")
        check_evidence(expected_agent, **pending.get("agent_evidence", {}))
    if kind == "firmware":
        hours = promotion.get("observation_hours", 72)
        if type(hours) is not int or hours not in {0, 72}:
            raise ValueError("Firmware observation window must be 0 or 72 hours")
        began = timestamp(observed.get("observation_started_at"))
        if began < timestamp(pending["prepared_at"]) or when - began < timedelta(hours=hours):
            raise ValueError("The firmware observation window has not passed")


def private_file(path, flags):
    descriptor = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    status = os.fstat(descriptor)
    if status.st_uid != os.getuid() or status.st_mode & 0o077:
        os.close(descriptor)
        raise ValueError(f"Restrict {path} to its owner")
    return descriptor


@contextmanager
def locked_state(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    status = directory.lstat()
    if directory.is_symlink() or status.st_uid != os.getuid() or status.st_mode & 0o077:
        raise ValueError(f"Restrict {directory} to its owner")
    with os.fdopen(private_file(directory / "lock", os.O_RDWR | os.O_CREAT), "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / "state.json"
        try:
            with os.fdopen(private_file(path, os.O_RDONLY)) as file:
                state = json.load(file)
        except FileNotFoundError:
            state = {"production": None, "pending": None}
        original = json.dumps(state, sort_keys=True)
        yield state
        if original != json.dumps(state, sort_keys=True):
            with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as file:
                temporary = Path(file.name)
                try:
                    json.dump(state, file, sort_keys=True, indent=2)
                    file.write("\n")
                    file.flush()
                    os.fsync(file.fileno())
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)


def require_pending(state):
    if state["pending"] is None:
        raise ValueError("No promotion is reserved")
    return state["pending"]


def local_command(args):
    with locked_state(args.state_dir) as state:
        if args.command == "status":
            print(json.dumps(state, indent=2))
            return
        if args.command == "record-agent":
            pending = require_pending(state)
            expected = pending["required_agent_version"]
            if not expected:
                raise ValueError("This promotion has no agent gate")
            evidence = {"version": args.version, "installed_at": args.installed_at, "received_at": args.received_at}
            check_evidence(expected, **evidence, earliest=timestamp(pending["prepared_at"]))
            pending["agent_evidence"] = evidence
            return
        if args.command == "cancel":
            pending = require_pending(state)
            if args.reservation_tag != pending["release_tag"]:
                raise ValueError("The tag must match the active reservation")
            # The owner supplies a separate record after checking whether a rollback is needed.
            if not args.reconciled:
                raise ValueError("Reconcile the observed live state before clearing a reservation")
            state["pending"] = None
            return

        manifest, manifest_sha = read_manifest(args.manifest)
        tag = token(args.reservation_tag, r"v[0-9]+\.[0-9]+\.[0-9]+", "Stable reservation tag")
        identity = {"manifest_sha": manifest_sha, "release_tag": tag, "candidate": manifest["source_commit"]}
        promotion = manifest["promotion"]
        if args.command == "prepare":
            if state["pending"] is not None:
                raise ValueError("A promotion is already reserved")
            state["pending"] = {
                **identity, "prepared_at": now().isoformat(),
                "required_agent_version": promotion.get("required_agent_version"),
                "observed": None,
            }
            return

        pending = require_pending(state)
        if any(pending[key] != value for key, value in identity.items()):
            raise ValueError("The manifest and tag must match the exact active reservation")
        if args.command == "deployment-inputs":
            if not deploys_worker(promotion):
                raise ValueError("The approved release does not include a Worker deployment")
            evidence = pending.get("agent_evidence", {})
            check_evidence(pending["required_agent_version"], **evidence)
            print(json.dumps({
                "candidate": identity["candidate"], "reservation_tag": tag, "manifest_sha": manifest_sha,
                "bundle_sha": manifest["assets"][BUNDLE]["sha256"],
                "agent_version": evidence.get("version", ""),
                "agent_installed_at": evidence.get("installed_at", ""),
                "telemetry_received_at": evidence.get("received_at", ""),
            }))
            return
        if args.command == "verify-production":
            with args.observed.open() as file:
                observed = json.load(file)
            check_production(manifest, pending, observed)
            pending["observed"] = observed
            return
        if not pending["observed"]:
            raise ValueError("Independent live verification is required before publication")
        if args.command == "publication-evidence":
            observed = pending["observed"]
            evidence = {
                **identity,
                "verified_at": observed["verified_at"],
                "required_checks": sorted(required_checks(promotion["kind"])),
                "worker_version": observed["worker_version"],
            }
            if deploys_worker(promotion):
                evidence["production_run_id"] = observed["production_run_id"]
            if "observation_started_at" in observed and promotion["kind"] == "firmware":
                evidence["observation_started_at"] = observed["observation_started_at"]
            validate_publication(manifest, manifest_sha, tag, evidence)
            print(json.dumps(evidence))
        if args.command == "complete":
            repo = token(args.repo, r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", "repository")
            confirm_native_publication(GitHub(repo), identity)
            state["production"] = {
                **pending["observed"], "release_tag": tag, "source_commit": identity["candidate"],
            }
            state["pending"] = None


def validate_publication(manifest, digest, tag, evidence):
    tag = token(tag, r"v[0-9]+\.[0-9]+\.[0-9]+", "Stable reservation tag")
    if (evidence.get("candidate"), evidence.get("manifest_sha"), evidence.get("release_tag")) != (
        manifest["source_commit"], digest, tag
    ):
        raise ValueError("Publication evidence must match the exact reserved release")
    kind = manifest["promotion"]["kind"]
    expected_fields = {"candidate", "manifest_sha", "release_tag", "verified_at", "required_checks", "worker_version"}
    if kind == "firmware":
        expected_fields.add("observation_started_at")
    if deploys_worker(manifest["promotion"]):
        expected_fields.add("production_run_id")
        production_run_id(evidence.get("production_run_id"))
    if set(evidence) != expected_fields or evidence["required_checks"] != sorted(required_checks(kind)):
        raise ValueError("Publication evidence is missing required production checks")
    verified = timestamp(evidence["verified_at"])
    if not now() - timedelta(hours=24) <= verified <= now() + timedelta(minutes=2):
        raise ValueError("Publication evidence must reflect recent production verification")
    observed_worker = worker_version(evidence["worker_version"])
    expected_worker = manifest["promotion"].get("expected_worker_version")
    if deploys_worker(manifest["promotion"]) and observed_worker == expected_worker:
        raise ValueError("The approved Worker change still has its previous deployment version")
    if not deploys_worker(manifest["promotion"]) and expected_worker and observed_worker != expected_worker:
        raise ValueError("The production Worker drifted from the approved baseline")
    if kind == "firmware":
        hours = manifest["promotion"].get("observation_hours", 72)
        if type(hours) is not int or hours not in {0, 72}:
            raise ValueError("Firmware observation window must be 0 or 72 hours")
        if verified - timestamp(evidence["observation_started_at"]) < timedelta(hours=hours):
            raise ValueError("The firmware observation window has not passed")


def production_run_id(value):
    if type(value) is not int or not 0 < value < 10**15:
        raise ValueError("Record the successful production workflow run ID")
    return value


def verify_production_run(github, manifest, digest, tag, evidence, maintainer):
    maintainer = token(maintainer, r"[A-Za-z0-9-]{1,39}", "protected production maintainer")
    run_id = production_run_id(evidence["production_run_id"])
    run_path = f"actions/runs/{run_id}"
    run = github.api(run_path)
    if (run["status"] != "completed" or run["conclusion"] != "success"
            or run["event"] != "workflow_dispatch" or run["head_branch"] != "stable"
            or run["head_sha"] != manifest["source_commit"]
            or run["head_repository"]["full_name"].casefold() != github.repo.casefold()
            or run["path"].split("@", 1)[0] != ".github/workflows/production.yml"):
        raise ValueError("The successful production workflow must run against the exact Stable source")
    if not any(
        review["state"] == "approved" and review["user"]["login"].casefold() == maintainer.casefold()
        and any(environment["name"] == "production" for environment in review["environments"])
        for review in github.api(f"{run_path}/approvals")
    ):
        raise ValueError("The production run has no recorded maintainer approval")
    jobs = github.api(f"{run_path}/attempts/{run['run_attempt']}/jobs?per_page=100")["jobs"]
    checks = [job["check_run_url"] for job in jobs if job["name"] == "deploy" and job["conclusion"] == "success"]
    if len(checks) != 1:
        raise ValueError("The production run is missing the successful deployment check")
    match = re.fullmatch(r"https://api\.github\.com/repos/" + re.escape(github.repo)
                         + r"/check-runs/([0-9]+)", checks[0], re.IGNORECASE)
    if not match:
        raise ValueError("The production deployment check belongs to a different repository")
    receipts = []
    for page in range(1, 11):
        annotations = github.api(f"check-runs/{match[1]}/annotations?per_page=100&page={page}")
        receipts.extend(json.loads(note["message"]) for note in annotations
                        if note["title"] == RECEIPT_TITLE and note["annotation_level"] == "notice")
        if len(annotations) < 100:
            break
    expected = {
        "candidate": manifest["source_commit"], "release_tag": tag, "manifest_sha": digest,
        "bundle_sha": manifest["assets"][BUNDLE]["sha256"], "worker_version": evidence["worker_version"],
    }
    if receipts != [expected]:
        raise ValueError("The reported Worker version was not activated by the approved production run for this release")


def released_manifest_bytes(github, tag):
    request = Request(f"https://github.com/{github.repo}/releases/download/{tag}/{MANIFEST}",
                      headers={"User-Agent": "JIDU6111-Promotion"})
    with urlopen(request, timeout=30) as response:
        data = response.read(METADATA_LIMIT + 1)
    if not data or len(data) > METADATA_LIMIT:
        raise ValueError("GitHub returned an invalid Stable manifest download")
    return data


def confirm_native_publication(github, identity):
    tag = identity["release_tag"]
    latest = github.api("releases/latest")
    if (latest.get("tag_name") != tag or channel_of(latest) != "stable"
            or is_pending(latest) or latest.get("immutable") is not True
            or latest.get("target_commitish") != identity["candidate"]
            or github.tag_commit(tag) != identity["candidate"]):
        raise ValueError("GitHub Latest does not identify this ready Stable release")
    data = released_manifest_bytes(github, tag)
    if hashlib.sha256(data).hexdigest() != identity["manifest_sha"]:
        raise ValueError("GitHub Latest manifest checksum differs from the verified promotion")


def verify_deployment(args):
    manifest, sha = read_manifest(args.manifest)
    if (args.candidate, args.manifest_sha, args.bundle_sha) != (
        manifest["source_commit"], sha, manifest["assets"][BUNDLE]["sha256"]
    ):
        raise ValueError("Deployment inputs must match the exact release manifest and verified bundle")
    if not deploys_worker(manifest["promotion"]):
        raise ValueError("The approved release does not include a Worker deployment")
    check_evidence(
        manifest["promotion"].get("required_agent_version"),
        args.agent_version, args.agent_installed_at, args.telemetry_received_at,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "jidu6111"
    parser.add_argument("--state-dir", type=Path, default=default)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "deployment-inputs", "verify-production",
                 "publication-evidence", "verify-publication-evidence", "complete"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--reservation-tag", required=True)
        if name == "verify-production":
            command.add_argument("--observed", type=Path, required=True)
        if name in {"verify-publication-evidence", "complete"}:
            command.add_argument("--repo", default=REPO)
        if name == "verify-publication-evidence":
            command.add_argument("--evidence", required=True)
            command.add_argument("--maintainer")
    commands.add_parser("status")
    agent = commands.add_parser("record-agent")
    for flag in ("version", "installed-at", "received-at"):
        agent.add_argument("--" + flag, required=True)
    cancel = commands.add_parser("cancel")
    cancel.add_argument("--reservation-tag", required=True)
    cancel.add_argument("--reconciled", action="store_true")
    verify = commands.add_parser("verify-deployment")
    verify.add_argument("--manifest", type=Path, required=True)
    for flag in ("candidate", "manifest-sha", "bundle-sha"):
        verify.add_argument("--" + flag, required=True)
    for flag in ("agent-version", "agent-installed-at", "telemetry-received-at"):
        verify.add_argument("--" + flag)
    args = parser.parse_args()
    try:
        if args.command == "verify-deployment":
            verify_deployment(args)
        elif args.command == "verify-publication-evidence":
            manifest, digest = read_manifest(args.manifest)
            evidence = json.loads(args.evidence)
            validate_publication(manifest, digest, args.reservation_tag, evidence)
            if deploys_worker(manifest["promotion"]):
                repo = token(args.repo, r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", "repository")
                verify_production_run(GitHub(repo), manifest, digest, args.reservation_tag, evidence, args.maintainer)
        else:
            local_command(args)
    except TypeError as error:
        print(f"Promotion error: invalid or missing evidence ({error})", file=sys.stderr)
        return 1
    except (KeyError, ValueError, OSError, AttributeError, subprocess.SubprocessError) as error:
        print(f"Promotion error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
