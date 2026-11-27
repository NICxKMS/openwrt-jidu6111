"""Stage and publish verified firmware assets using native GitHub Releases."""

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

REPO = "NICxKMS/openwrt-jidu6111"
MANIFEST = "release-manifest.json"
MANAGED = "<!-- jidu6111-managed -->"
PENDING = "<!-- jidu6111-publication-pending -->"
BOARD = "jiorouter,ax6000-jidu6111"
HEX40 = re.compile(r"[a-f0-9]{40}")
HEX64 = re.compile(r"[a-f0-9]{64}")
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}")
APK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~@-]*[.]apk")
NUMBER = r"(?:0|[1-9][0-9]*)"
VERSION = rf"v{NUMBER}\.{NUMBER}\.{NUMBER}"
TAGS = {
    "stable": re.compile(VERSION),
    "development": re.compile(rf"{VERSION}-dev\.{NUMBER}\.{NUMBER}"),
}


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def checked_file(name):
    if not isinstance(name, str) or not NAME.fullmatch(name) or name in {".", ".."}:
        raise ValueError(f"Invalid asset filename: {name!r}")
    return name


def verify_feed_layout(path):
    names = set()
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = member.name
            if (name in names or not member.isfile() or member.size < 1
                    or not (name == "packages.adb" or APK_NAME.fullmatch(name))):
                raise ValueError(f"Unexpected feed member: {name}")
            names.add(name)
    if "packages.adb" not in names or len(names) < 2:
        raise ValueError("A feed requires a signed index and package files")


def verify_local(directory, commit, *, check_feeds=True):
    manifest_file = directory / MANIFEST
    if manifest_file.is_symlink() or manifest_file.stat().st_size > 1024 * 1024:
        raise ValueError("Invalid release manifest file")
    manifest = json.loads(manifest_file.read_text())
    if not isinstance(manifest, dict) or manifest.get("schema") != 1 or manifest.get("source_commit") != commit:
        raise ValueError("Release manifest has the wrong schema or source commit")
    assets, profiles = manifest.get("assets"), manifest.get("profiles")
    if not isinstance(assets, dict) or not assets or not isinstance(profiles, list) or not profiles:
        raise ValueError("Release manifest requires profiles and assets")
    for name, expected in assets.items():
        path = directory / checked_file(name)
        if name == MANIFEST or path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or invalid asset: {name}")
        if (not isinstance(expected, dict) or path.stat().st_size < 1
                or path.stat().st_size != expected.get("size") or digest(path) != expected.get("sha256")):
            raise ValueError(f"Asset size or checksum mismatch: {name}")
    if {path.name for path in directory.iterdir()} != {MANIFEST, *assets}:
        raise ValueError("Staging directory must contain only manifest assets")
    ids = set()
    for profile in profiles:
        if (not isinstance(profile, dict) or not isinstance(profile.get("id"), str) or not NAME.fullmatch(profile["id"])
                or profile["id"] in ids or profile.get("board") != BOARD
                or profile.get("architecture") != "aarch64_cortex-a53"
                or not NAME.fullmatch(str(profile.get("kernel", "")).replace("~", "-"))
                or not HEX64.fullmatch(str(profile.get("key_sha256", "")))):
            raise ValueError("Invalid firmware compatibility profile")
        ids.add(profile["id"])
        feed = checked_file(profile.get("feed"))
        images = profile.get("images")
        if feed not in assets or not feed.endswith(".tar.gz") or not isinstance(images, list) or not images:
            raise ValueError("Profile requires a declared feed bundle and images")
        radios = set()
        for image in images:
            if (not isinstance(image, dict) or image.get("radio") not in {"dual-band", "wcss-off"}
                    or image["radio"] in radios or checked_file(image.get("file")) not in assets
                    or not image["file"].endswith(".bin")):
                raise ValueError("Profile has an undeclared image or invalid radio")
            radios.add(image["radio"])
        if check_feeds:
            verify_feed_layout(directory / feed)
    return manifest


def channel_of(entry):
    body = (entry.get("body") or "").splitlines()
    channel = "development" if entry.get("prerelease") else "stable"
    if MANAGED in body and TAGS[channel].fullmatch(entry.get("tag_name", "")):
        return channel
    return None


def is_pending(entry):
    return entry["draft"] or PENDING in (entry.get("body") or "").splitlines()


def published_on(entry):
    return (entry.get("published_at") or "", entry["id"])


def json_pages(output):
    decoder = json.JSONDecoder()
    position = 0
    pages = []
    while remainder := output[position:].lstrip():
        skipped = len(output) - position - len(remainder)
        page, end = decoder.raw_decode(output, position + skipped)
        pages.append(page)
        position = end
    return pages


class GitHub:
    def __init__(self, repo):
        self.repo = repo
        self.base = f"repos/{repo}"

    def api(self, path, *, data=None, method=None, paginate=False):
        command = ["gh", "api", f"{self.base}/{path}"]
        if method:
            command += ["--method", method]
        if data is not None:
            command += ["--input", "-"]
        if paginate:
            command += ["--paginate"]
        result = subprocess.run(command, check=True, capture_output=True, text=True,
                                input=json.dumps(data) if data is not None else None)
        if paginate:
            return json_pages(result.stdout)
        return json.loads(result.stdout) if result.stdout else None

    def releases(self):
        return [release for page in self.api("releases?per_page=100", paginate=True) for release in page]

    def branch_head(self, branch):
        return self.api(f"git/ref/heads/{branch}")["object"]["sha"]

    def tag_commit(self, tag, *, missing_ok=False):
        try:
            target = self.api(f"git/ref/tags/{tag}")["object"]
        except subprocess.CalledProcessError as error:
            if missing_ok and "HTTP 404" in error.stderr:
                return None
            raise
        if target["type"] == "tag":
            target = self.api(f"git/tags/{target['sha']}")["object"]
        if target["type"] != "commit":
            raise ValueError("Release tag does not resolve to a source commit")
        return target["sha"]

    def patch(self, entry, **data):
        return self.api(f"releases/{entry['id']}", data=data, method="PATCH")

    def delete(self, entry):
        self.api(f"releases/{entry['id']}", method="DELETE")

    def create(self, channel, tag, commit, notes):
        body = f"{MANAGED}\n{PENDING}\n\n{notes.strip()}"
        label = "Development" if channel == "development" else "Stable"
        return self.api("releases", method="POST", data={
            "tag_name": tag, "target_commitish": commit, "draft": True,
            "prerelease": channel == "development", "name": f"JIDU6111 {label} {tag}",
            "body": body, "make_latest": "false",
        })

    def upload(self, tag, path):
        subprocess.run(["gh", "release", "upload", tag, str(path), "--repo", self.repo], check=True)

    def download(self, entry, directory):
        subprocess.run(["gh", "release", "download", entry["tag_name"], "--repo", self.repo,
                        "--dir", str(directory), "--pattern", "*"], check=True)

    def verify_draft(self, entry, commit, approved_digest=None):
        with tempfile.TemporaryDirectory(prefix="jidu6111-release-") as temporary:
            directory = pathlib.Path(temporary)
            self.download(entry, directory)
            manifest = verify_local(directory, commit)
            if approved_digest and digest(directory / MANIFEST) != approved_digest:
                raise ValueError("The staged manifest differs from the approved checksum")
            return {name: {"size": (directory / name).stat().st_size, "sha256": digest(directory / name)}
                    for name in (MANIFEST, *manifest["assets"])}

    def verify_public(self, entry, assets):
        tag = entry["tag_name"]
        headers = {"User-Agent": "JIDU6111-release-verifier"}
        with tempfile.TemporaryDirectory(prefix="jidu6111-public-") as temporary:
            path = pathlib.Path(temporary) / "asset"
            for name, expected in assets.items():
                url = f"https://github.com/{self.repo}/releases/download/{tag}/{name}"
                for retry in range(3):
                    try:
                        request = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(request, timeout=120) as remote, path.open("wb") as output:
                            shutil.copyfileobj(remote, output)
                        break
                    except OSError:
                        if retry == 2:
                            raise
                if path.stat().st_size != expected["size"] or digest(path) != expected["sha256"]:
                    raise ValueError(f"Public asset checksum mismatch: {name}")

    def verify_discovery(self, entry, channel):
        suffix = "latest" if channel == "stable" else "?per_page=100"
        separator = "/" if channel == "stable" else ""
        url = f"https://api.github.com/{self.base}/releases{separator}{suffix}"
        headers = {"User-Agent": "JIDU6111-release-verifier", "Cache-Control": "no-cache"}
        for attempt in range(5):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as remote:
                    response = json.load(remote)
                entries = [response] if channel == "stable" else response
                current = max(
                    (candidate for candidate in entries if channel_of(candidate) == channel
                     and not is_pending(candidate)),
                    key=published_on,
                    default=None,
                )
                if current and current["id"] == entry["id"]:
                    return
            except OSError:
                pass
            if attempt < 4:
                time.sleep(2)
        raise ValueError("GitHub public discovery has not exposed the verified replacement")


def get_managed(entries, channel, tag):
    for entry in entries:
        if entry.get("tag_name") == tag:
            if channel_of(entry) != channel:
                raise ValueError(f"{tag} belongs to a release outside this channel")
            return entry
    return None


def guard(github, entries, channel, tag, commit):
    if github.branch_head(channel) != commit:
        raise ValueError(f"Candidate does not match the {channel} branch head")
    reservations = [
        entry for entry in entries
        if channel_of(entry) == "stable" and is_pending(entry) and entry["tag_name"] != tag
    ]
    if reservations:
        raise ValueError(f"Stable promotion already reserved by {reservations[0]['tag_name']}")


def stage(github, channel, tag, commit, directory, notes):
    entries = github.releases()
    guard(github, entries, channel, tag, commit)
    entry = get_managed(entries, channel, tag)
    if entry and (not entry["draft"] or not is_pending(entry) or entry["target_commitish"] != commit):
        raise ValueError("Choose a new release tag for different or already published content")
    manifest = verify_local(directory, commit) if directory else None
    if not entry:
        if channel == "stable" and directory:
            raise ValueError("Reserve the Stable draft with the serialized workflow before staging")
        if github.tag_commit(tag, missing_ok=True):
            raise ValueError("This version tag already exists")
        entry = github.create(channel, tag, commit, notes)
    if manifest is not None:
        uploaded = {asset["name"]: asset for asset in entry["assets"]}
        expected = set(manifest["assets"]) | {MANIFEST}
        if uploaded.keys() - expected:
            raise ValueError("The draft already contains assets outside the candidate")
        for name in [*sorted(manifest["assets"]), MANIFEST]:
            path = directory / name
            if name not in uploaded:
                github.upload(tag, path)
                continue
            asset = uploaded[name]
            if asset["size"] != path.stat().st_size or asset.get("digest") != f"sha256:{digest(path)}":
                raise ValueError(f"Draft asset differs from the candidate: {name}")


def guard_development_order(entries, target):
    if channel_of(target) != "development":
        return
    if any(channel_of(entry) == "development" and not is_pending(entry)
           and entry["id"] > target["id"] for entry in entries):
        raise ValueError("A newer candidate has already been verified")


def verify_consumed_development(github, candidate, assets):
    candidate_commit = github.tag_commit(candidate["tag_name"])
    previous = github.verify_draft(candidate, candidate_commit)
    firmware_assets = {
        name: info for name, info in previous.items()
        if name.endswith((".bin", ".tar.gz")) and name != "monitor-bundle.tar.gz"
    }
    if not firmware_assets or any(assets.get(name) != expected for name, expected in firmware_assets.items()):
        raise ValueError("The consumed Development firmware and feed must match Stable exactly")


def publish(github, channel, tag, commit, approved_digest=None, consumed_tag=None):
    entries = github.releases()
    guard(github, entries, channel, tag, commit)
    target = get_managed(entries, channel, tag)
    if not target or target["target_commitish"] != commit:
        raise ValueError(f"No managed {channel} release staged at {commit}")
    guard_development_order(entries, target)
    candidate = None
    if consumed_tag is not None:
        candidate = get_managed(entries, "development", consumed_tag)
        if channel != "stable" or (candidate and is_pending(candidate)) or (not candidate and is_pending(target)):
            raise ValueError("The consumed tag must be the verified Development release")
    if not target["draft"] and github.tag_commit(tag) != commit:
        raise ValueError("Published tag does not match the verified source commit")
    if is_pending(target):
        assets = github.verify_draft(target, commit, approved_digest) if approved_digest else github.verify_draft(target, commit)
        if candidate:
            verify_consumed_development(github, candidate, assets)
        current = github.releases()
        guard(github, current, channel, tag, commit)
        guard_development_order(current, target)
        if target["draft"]:
            if github.tag_commit(tag, missing_ok=True) not in (None, commit):
                raise ValueError("Existing version tag points to another commit")
            target = github.patch(target, draft=False, make_latest="false")
            if github.tag_commit(tag) != commit:
                raise ValueError("GitHub assigned an unexpected release tag target")
        if target.get("immutable") is not True:
            raise ValueError("Enable immutable GitHub releases before publishing managed assets")
        github.verify_public(target, assets)
        current = github.releases()
        guard(github, current, channel, tag, commit)
        guard_development_order(current, target)
        body = "\n".join(line for line in (target.get("body") or "").splitlines() if line != PENDING)
        target = github.patch(target, body=body, make_latest="true" if channel == "stable" else "false")
    elif approved_digest:
        assets = github.verify_draft(target, commit, approved_digest)
        if candidate:
            verify_consumed_development(github, candidate, assets)
    github.verify_discovery(target, channel)
    for entry in entries:
        if entry["id"] == target["id"]:
            continue
        previous = channel_of(entry) == channel
        if previous and (entry["id"] > target["id"] or
                         (not is_pending(entry) and published_on(entry) > published_on(target))):
            continue
        if previous or (candidate and entry["id"] == candidate["id"]):
            if channel == "development":
                guard(github, github.releases(), channel, tag, commit)
            github.delete(entry)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("operation", choices=("reserve", "stage", "fetch", "publish"))
    parser.add_argument("--channel", choices=TAGS, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--directory", type=pathlib.Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--consume-development")
    parser.add_argument("--notes-file", type=pathlib.Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("Repository must be owner/name")
    if not TAGS[args.channel].fullmatch(args.tag) or not HEX40.fullmatch(args.commit):
        parser.error("Use an exact source SHA and a versioned stable or development tag")
    if args.manifest_sha256 and not HEX64.fullmatch(args.manifest_sha256):
        parser.error("Use a SHA-256 manifest digest")
    if args.operation in {"stage", "fetch"} and args.directory is None:
        parser.error("--directory is required")
    if args.operation == "reserve" and (args.channel != "stable" or args.directory is not None):
        parser.error("Reserve creates a Stable draft without assets")
    if args.operation == "publish" and not args.manifest_sha256:
        parser.error("Publication requires the SHA-256 from the verified draft")

    github = GitHub(args.repo)
    try:
        if args.operation in {"reserve", "stage"}:
            notes = args.notes_file.read_text() if args.notes_file else (
                "Firmware and signed package feeds. See the release manifest for exact compatibility."
            )
            stage(github, args.channel, args.tag, args.commit, args.directory, notes)
        elif args.operation == "fetch":
            entry = get_managed(github.releases(), args.channel, args.tag)
            if not entry or entry["target_commitish"] != args.commit:
                raise ValueError("No managed release staged at the requested commit")
            github.download(entry, args.directory)
            verify_local(args.directory, args.commit)
        else:
            publish(github, args.channel, args.tag, args.commit, args.manifest_sha256, args.consume_development)
    except subprocess.CalledProcessError as error:
        print(error.stderr or str(error), file=sys.stderr)
        return 1
    except (ValueError, OSError, tarfile.TarError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
