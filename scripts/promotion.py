import argparse
import hashlib
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from firmware_artifacts import BUILD_PROFILES, RADIOS, TARGET, output_json
from release_workflow import REPO, GitHub, HEX40, HEX64, MANIFEST, TAGS, digest, eligible, get_managed, verify_local

EVIDENCE = "hardware-evidence.json"
FUNCTIONS = {"boot", "reboot", "memory", "wifi", "network", "packages", "local_monitoring", "recovery"}


def git_file(commit: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], text=True)


def verify_candidate(directory: Path, manifest: dict, key_fingerprint: str) -> None:
    commit = manifest["source_commit"]
    feeds = {
        name: url.rsplit("^", 1)[-1]
        for method, name, url in (line.split() for line in git_file(commit, "sources/feeds.conf").splitlines()
                                  if line.strip() and not line.lstrip().startswith("#"))
        if method == "src-git"
    }
    if "nicx_monitor" not in feeds or not all(HEX40.fullmatch(pin) for pin in feeds.values()):
        raise ValueError("Firmware release requires immutable feed pins")
    openwrt = subprocess.check_output(
        ["git", "hash-object", "-t", "commit", "--stdin"],
        input=git_file(commit, "sources/openwrt.commit"), text=True).strip()
    if (set(manifest) - {"schema", "source_commit", "profiles", "assets", "promotion"}
            or {p["id"] for p in manifest["profiles"]} != set(BUILD_PROFILES)
            or not HEX64.fullmatch(key_fingerprint)):
        raise ValueError("Expected both firmware profiles and a configured trusted signing fingerprint")
    referenced = {EVIDENCE} if "promotion" in manifest else set()
    source_paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", commit, "--", "sources"], text=True
    ).splitlines()
    patches = {path: hashlib.sha256(subprocess.check_output(["git", "show", f"{commit}:{path}"])).hexdigest()
               for path in source_paths if path.endswith(".patch")}
    for profile in manifest["profiles"]:
        if {image["radio"] for image in profile["images"]} != set(RADIOS):
            raise ValueError("Both radio variants are required for each release profile")
        if profile["key_sha256"] != key_fingerprint:
            raise ValueError("Firmware package key differs from the approved release key")
        for image in profile["images"]:
            radio = image["radio"]
            if (image["file"] != f"jidu6111-{profile['id']}-{radio}-sysupgrade.bin"
                    or image["type"] != "sysupgrade"):
                raise ValueError("Firmware asset name must identify its compiler, radio and image type")
        buildinfo = profile["buildinfo"]
        files = {buildinfo, profile["feed"], *(image["file"] for image in profile["images"])}
        if len(files) != 4 or files & referenced or not files <= manifest["assets"].keys():
            raise ValueError("Each profile requires distinct declared images, feed and build information")
        referenced.update(files)
        info = json.loads((directory / buildinfo).read_text())
        config_hash = hashlib.sha256(info["resolved_config"].encode()).hexdigest()
        abi = profile["kernel"].split("~")[1].rsplit("-r", 1)[0]
        if (profile["target"] != TARGET or profile["config_sha256"] != config_hash or profile["kernel_abi"] != abi
                or not HEX64.fullmatch(info["kernel_source_sha256"]) or info["kernel"]["vermagic"] != abi
                or info["kernel"]["version"] != profile["kernel"].split("~")[0]
                or info["patch_sha256"] != patches or not info["resolved_kernel_config"]
                or not info["tool_versions"] or not info["build_host"]):
            raise ValueError("Incomplete firmware compiler, configuration or patch provenance")
        if (info["source_commit"] != commit or info["openwrt_commit"] != openwrt
                or info["feed_revisions"] != feeds or profile["monitoring"]["commit"] != feeds["nicx_monitor"]):
            raise ValueError("Build information does not match the pinned firmware source")
    if referenced != manifest["assets"].keys():
        raise ValueError("Release contains unreferenced assets")


def timestamp(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() != timedelta(0):
        raise ValueError("Hardware evidence timestamps must use UTC")
    return moment


def verify_hardware(evidence: dict, manifest: dict, minimum: timedelta) -> None:
    images = {
        (profile["id"], image["radio"]): manifest["assets"][image["file"]]["sha256"]
        for profile in manifest["profiles"] for image in profile["images"]
    }
    if evidence["source_commit"] != manifest["source_commit"]:
        raise ValueError("Hardware evidence must name the exact firmware source")
    seen = set()
    for record in evidence["variants"]:
        variant = (record["compiler"], record["radio"])
        start, end = timestamp(record["started_at"]), timestamp(record["ended_at"])
        if (variant in seen or variant not in images or record["image_sha256"] != images[variant]
                or not start < end <= datetime.now(timezone.utc) or end - start < minimum
                or set(record["checks"]) != FUNCTIONS or any(value != "pass" for value in record["checks"].values())
                or not all(record.get(field, "").strip() for field in ("configuration", "workload", "observations"))):
            raise ValueError(f"Incomplete hardware evidence for {variant[0]} / {variant[1]}")
        seen.add(variant)
    if seen != images.keys():
        raise ValueError("Stable hardware evidence must cover every published variant")


def beta_manifest(github: GitHub, directory: Path, tag: str, commit: str) -> dict:
    if not TAGS["beta"].fullmatch(tag):
        raise ValueError("Promotion requires a versioned Beta tag")
    release = get_managed(github.releases(), "beta", tag)
    if release is None or not eligible(release, "beta") or github.tag_commit(tag) != commit:
        raise ValueError("Promotion requires a verified immutable Beta at the exact source commit")
    github.download(release, directory, MANIFEST)
    path = directory / MANIFEST
    digests = [asset["digest"] for asset in release["assets"] if asset["name"] == MANIFEST]
    if digests != [f"sha256:{digest(path)}"]:
        raise ValueError("Beta manifest does not match its published checksum")
    return json.loads(path.read_text())


def verify_promotion(directory: Path, manifest: dict, beta: dict) -> None:
    if manifest["promotion"]["beta_tag"].split("-beta.")[0] != manifest["promotion"]["stable_tag"]:
        raise ValueError("Stable must use the same base version as its Beta")
    original = {key: value for key, value in manifest.items() if key != "promotion"}
    original["assets"] = {name: meta for name, meta in manifest["assets"].items() if name != EVIDENCE}
    for profile in manifest["profiles"]:
        if any(image.get("hardware_verification") != "stability-tested" for image in profile["images"]):
            raise ValueError("Stable variants must declare stability-tested hardware status")
    original["profiles"] = [
        {**profile, "images": [{**image, "hardware_verification": "not-tested"} for image in profile["images"]]}
        for profile in manifest["profiles"]
    ]
    if original != beta:
        raise ValueError("Stable firmware, signed feeds and build provenance must match Beta exactly")
    evidence = json.loads((directory / EVIDENCE).read_text())
    verify_hardware(evidence, manifest, timedelta(hours=72))


def main() -> int:
    parser = argparse.ArgumentParser(description='Verify firmware provenance and Stable hardware evidence.')
    parser.add_argument("operation", choices=("prepare", "verify"))
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--beta")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if not HEX40.fullmatch(args.commit):
        parser.error("Use an exact source commit")
    try:
        manifest = verify_local(args.directory, args.commit)
        if args.operation == "prepare":
            if not TAGS["stable"].fullmatch(args.tag) or not args.beta or not args.evidence:
                parser.error("Prepare requires a Stable tag, Beta tag and local hardware evidence")
            if "promotion" in manifest or EVIDENCE in manifest["assets"]:
                raise ValueError("Prepare Stable from a fresh copy of the Beta assets")
            evidence = args.evidence.read_bytes()
            manifest["promotion"] = {"beta_tag": args.beta, "stable_tag": args.tag}
            manifest["assets"][EVIDENCE] = {"sha256": hashlib.sha256(evidence).hexdigest(), "size": len(evidence)}
            verify_hardware(json.loads(evidence), manifest, timedelta(hours=72))
            if args.beta.split("-beta.")[0] != args.tag or not TAGS["beta"].fullmatch(args.beta):
                raise ValueError("Stable must use the same base version as its Beta")
            for profile in manifest["profiles"]:
                for image in profile["images"]:
                    image["hardware_verification"] = "stability-tested"
            (args.directory / EVIDENCE).write_bytes(evidence)
            output_json(args.directory / MANIFEST, manifest)
            return 0

        verify_candidate(args.directory, manifest, os.environ.get("FIRMWARE_KEY_SHA256", ""))
        if TAGS["beta"].fullmatch(args.tag) and "promotion" not in manifest:
            if any(image.get("hardware_verification") != "not-tested"
                   for profile in manifest["profiles"] for image in profile["images"]):
                raise ValueError("Attribute Beta hardware observations in the release notes")
            return 0
        if not TAGS["stable"].fullmatch(args.tag) or manifest["promotion"]["stable_tag"] != args.tag:
            raise ValueError("Release tag and promotion metadata differ")
        with TemporaryDirectory(prefix="jidu6111-beta-") as temporary:
            beta = beta_manifest(GitHub(os.environ.get("GITHUB_REPOSITORY", REPO)), Path(temporary),
                                 manifest["promotion"]["beta_tag"], args.commit)
        verify_promotion(args.directory, manifest, beta)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(getattr(error, "stderr", None) or str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
