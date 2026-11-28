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
    "beta": re.compile(rf"{VERSION}-beta\.[1-9][0-9]*"),
}


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


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
    if (not isinstance(manifest, dict) or type(manifest.get("schema")) is not int
            or manifest["schema"] != 1 or manifest.get("source_commit") != commit):
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
                or not isinstance(profile.get("kernel"), str)
                or not NAME.fullmatch(profile["kernel"].replace("~", "-"))
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
    channel = "beta" if entry.get("prerelease") else "stable"
    if MANAGED in body and TAGS[channel].fullmatch(entry.get("tag_name", "")):
        return channel
    return None


def is_pending(entry):
    return entry["draft"] or PENDING in (entry.get("body") or "").splitlines()


def version_key(tag: str) -> tuple[int, ...]:
    return tuple(map(int, re.findall(r"[0-9]+", tag)))


def eligible(entry, channel: str) -> bool:
    return channel_of(entry) == channel and entry.get("immutable") is True and not is_pending(entry)


def should_mark_latest(entries, channel: str, tag: str) -> bool:
    return channel == "stable" and all(
        version_key(entry["tag_name"]) <= version_key(tag) for entry in entries if eligible(entry, "stable")
    )


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

    def create(self, channel, tag, commit, notes):
        body = f"{MANAGED}\n{PENDING}\n\n{notes.strip()}"
        label = "Beta" if channel == "beta" else "Stable"
        return self.api("releases", method="POST", data={
            "tag_name": tag, "target_commitish": commit, "draft": True,
            "prerelease": channel == "beta", "name": f"JIDU6111 {label} {tag}",
            "body": body, "make_latest": "false",
        })

    def upload(self, tag, path):
        subprocess.run(["gh", "release", "upload", tag, str(path), "--repo", self.repo], check=True)

    def download(self, entry, directory, pattern="*"):
        subprocess.run(["gh", "release", "download", entry["tag_name"], "--repo", self.repo,
                        "--dir", str(directory), "--pattern", pattern], check=True, stdout=sys.stderr)

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


def get_managed(entries, channel, tag):
    for entry in entries:
        if entry.get("tag_name") == tag:
            if channel_of(entry) != channel:
                raise ValueError(f"{tag} belongs to a release outside this channel")
            return entry
    return None


def stage(github, channel: str, tag: str, commit: str, directory: pathlib.Path, notes: str) -> None:
    manifest = verify_local(directory, commit)
    if github.api("immutable-releases").get("enabled") is not True:
        raise ValueError("Enable immutable GitHub releases before staging")
    entry = get_managed(github.releases(), channel, tag)
    if entry and (not entry["draft"] or entry["target_commitish"] != commit):
        raise ValueError("Choose a new tag for different or published content")
    tagged_commit = github.tag_commit(tag, missing_ok=True)
    if tagged_commit is not None and (entry is None or tagged_commit != commit):
        raise ValueError("This version tag already exists")
    if entry is None:
        entry = github.create(channel, tag, commit, notes)
    uploaded = {asset["name"]: asset for asset in entry["assets"]}
    names = [*sorted(manifest["assets"]), MANIFEST]
    if uploaded.keys() - set(names):
        raise ValueError("The draft already contains undeclared assets")
    for name in names:
        path = directory / name
        if name not in uploaded:
            github.upload(tag, path)
        elif uploaded[name].get("digest") != f"sha256:{digest(path)}":
            raise ValueError(f"Draft asset differs from the candidate: {name}")
    if tagged_commit is None:
        github.api("git/refs", method="POST", data={"ref": f"refs/tags/{tag}", "sha": commit})


def asset_receipt(entry) -> str:
    assets = {}
    for asset in entry["assets"]:
        name = checked_file(asset["name"])
        sha256 = asset.get("digest") or ""
        if (name in assets or asset["state"] != "uploaded" or asset["size"] <= 0
                or not sha256.startswith("sha256:") or not HEX64.fullmatch(sha256[7:])):
            raise ValueError("GitHub draft asset is incomplete")
        assets[name] = (asset["id"], asset["size"], sha256)
    if MANIFEST not in assets:
        raise ValueError("Missing GitHub manifest asset")
    payload = json.dumps([entry["id"], entry["target_commitish"], assets], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def match_download(entry, directory: pathlib.Path, manifest: dict) -> str:
    receipt = asset_receipt(entry)
    wanted = {MANIFEST: {"size": (directory / MANIFEST).stat().st_size, "sha256": digest(directory / MANIFEST)},
              **manifest["assets"]}
    actual = {asset["name"]: {"size": asset["size"], "sha256": asset["digest"][7:]} for asset in entry["assets"]}
    if wanted != actual:
        raise ValueError("Downloaded files differ from the GitHub asset digests")
    return receipt


def publish(github, channel: str, tag: str, commit: str, receipt: str) -> None:
    entries = github.releases()
    target = get_managed(entries, channel, tag)
    if not target or target["target_commitish"] != commit or asset_receipt(target) != receipt:
        raise ValueError("Release changed after independent artifact verification")
    if github.tag_commit(tag, missing_ok=True) != commit:
        raise ValueError("Release tag differs from the verified source")
    if target["draft"]:
        target = github.patch(target, draft=False, make_latest="false")
    if asset_receipt(target) != receipt:
        raise ValueError("Published assets differ from the independently verified draft")
    if target.get("immutable") is not True or github.tag_commit(tag) != commit:
        raise ValueError("GitHub release is not immutable at the verified commit")
    if not is_pending(target):
        return
    assets = {asset["name"]: {"size": asset["size"], "sha256": asset["digest"][7:]} for asset in target["assets"]}
    github.verify_public(target, assets)
    body = "\n".join(line for line in (target.get("body") or "").splitlines() if line != PENDING)
    github.patch(target, body=body, make_latest="true" if should_mark_latest(entries, channel, tag) else "false")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("operation", choices=("stage", "fetch", "publish"))
    parser.add_argument("--channel", choices=TAGS, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--directory", type=pathlib.Path)
    parser.add_argument("--receipt")
    parser.add_argument("--notes-file", type=pathlib.Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("Repository must be owner/name")
    if not TAGS[args.channel].fullmatch(args.tag) or not HEX40.fullmatch(args.commit):
        parser.error("Use an exact source SHA and a versioned Stable or Beta tag")
    if args.operation in {"stage", "fetch"} and args.directory is None:
        parser.error("--directory is required")
    if args.operation == "publish" and not HEX64.fullmatch(args.receipt or ""):
        parser.error("Publication requires the receipt from independent verification")

    github = GitHub(args.repo)
    try:
        if args.operation == "stage":
            notes = args.notes_file.read_text() if args.notes_file else (
                "Firmware and matching signed APK feeds. See the manifest and repository documentation."
            )
            stage(github, args.channel, args.tag, args.commit, args.directory, notes)
        elif args.operation == "fetch":
            entry = get_managed(github.releases(), args.channel, args.tag)
            if not entry or entry["target_commitish"] != args.commit:
                raise ValueError("No managed release for the requested commit")
            github.download(entry, args.directory)
            print(match_download(entry, args.directory, verify_local(args.directory, args.commit)))
        else:
            publish(github, args.channel, args.tag, args.commit, args.receipt)
    except subprocess.CalledProcessError as error:
        print(error.stderr or str(error), file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
