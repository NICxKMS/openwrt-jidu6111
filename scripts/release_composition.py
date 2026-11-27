"""Choose verification scope and assemble release provenance from selected source."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from release_workflow import HEX40, MANIFEST, digest, verify_local

MONITOR = "nicx-router-monitor/"
ALL = {"firmware", "packages", "dashboard", "worker", "agent", "database", "release"}
COMPONENT_PATHS = {
    "dashboard": MONITOR + "apps/dashboard",
    "worker": MONITOR + "apps/worker",
    "agent": MONITOR + "openwrt",
    "database": MONITOR + "supabase/migrations",
}
DOC_SUFFIXES = (".md", ".rst", ".txt")


def components(paths):
    result = set()
    for path in paths:
        if path.endswith(DOC_SUFFIXES):
            continue
        if path.startswith(("config/", "sources/", "scripts/configure-", "scripts/bootstrap-",
                            "scripts/build-firmware", "scripts/firmware_artifacts")):
            result.update(("firmware", "packages"))
        elif path.startswith(MONITOR + "packages/shared/"):
            result.update(("dashboard", "worker", "agent", "database"))
        elif path.startswith(COMPONENT_PATHS["database"] + "/"):
            result.update(("dashboard", "worker", "agent", "database"))
        elif any(path.startswith(directory + "/") for directory in COMPONENT_PATHS.values()):
            result.update(name for name, directory in COMPONENT_PATHS.items()
                          if path.startswith(directory + "/"))
            if path.startswith(COMPONENT_PATHS["agent"] + "/"):
                result.add("packages")
        elif path.startswith((".github/", "scripts/", "Makefile")):
            result.add("release")
        else:
            return ALL.copy()
    return result


def git(*args, text=True):
    return subprocess.check_output(["git", *args], text=text)


def monitor_provenance(commit):
    versions = {}
    for name, path in COMPONENT_PATHS.items():
        last_change = git("log", "-1", "--format=%H", commit, "--", path).strip()
        if last_change:
            versions[name] = {"source_commit": last_change}
    if "agent" in versions:
        versions["agent"]["packages"] = {}
        for name in ("nicx-telemetry", "luci-app-nicx-telemetry"):
            recipe = git("show", f"{commit}:{COMPONENT_PATHS['agent']}/{name}/Makefile")
            version = re.search(r"^PKG_VERSION\s*:?=\s*(\S+)", recipe, re.MULTILINE)[1]
            release = re.search(r"^PKG_RELEASE\s*:?=\s*(\S+)", recipe, re.MULTILINE)[1]
            versions["agent"]["packages"][name] = f"{version}-r{release}"
    if "database" in versions:
        directory = COMPONENT_PATHS["database"]
        paths = git("ls-tree", "--name-only", "-r", commit, directory).splitlines()
        versions["database"]["migrations"] = [
            {"file": Path(path).name, "sha256": hashlib.sha256(git("show", f"{commit}:{path}", text=False)).hexdigest()}
            for path in paths if path.endswith(".sql")
        ]
    return versions


def compose(args):
    manifest_path = args.directory / MANIFEST
    old = json.loads(manifest_path.read_text())
    manifest = verify_local(args.directory, old["source_commit"])
    for profile in manifest["profiles"]:
        profile.setdefault("firmware_source_commit", old["source_commit"])
    manifest["source_commit"] = args.commit
    if args.promotion:
        manifest["promotion"] = json.loads(args.promotion.read_text())
    if args.observed_components:
        manifest["monitoring"] = json.loads(args.observed_components.read_text())
    elif not args.promotion:
        manifest["monitoring"] = monitor_provenance(args.commit)
    elif "monitoring" not in manifest:
        raise ValueError("Provide reviewed public component pins with --observed-components for Stable")
    target = args.directory / "monitor-bundle.tar.gz"
    if args.bundle:
        if target.resolve() == args.bundle.resolve():
            raise ValueError("Provide the verified bundle from outside the release directory")
        if target.exists():
            raise ValueError("Compose into a directory without a previous Worker bundle")
        shutil.copyfile(args.bundle, target)
        manifest["assets"][target.name] = {"sha256": digest(target), "size": target.stat().st_size}
    with tempfile.TemporaryDirectory(dir=args.directory.parent, prefix="release-manifest-") as stage:
        temporary = Path(stage) / MANIFEST
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        temporary.replace(manifest_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scope = sub.add_parser("scope")
    scope.add_argument("--base", required=True)
    scope.add_argument("--commit", required=True)
    assemble = sub.add_parser("compose")
    assemble.add_argument("--commit", required=True)
    assemble.add_argument("--directory", type=Path, required=True)
    assemble.add_argument("--promotion", type=Path)
    assemble.add_argument("--observed-components", type=Path)
    assemble.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    if not HEX40.fullmatch(args.commit) or (args.command == "scope" and not HEX40.fullmatch(args.base)):
        parser.error("Use exact source commit SHAs")
    try:
        if args.command == "scope":
            files = git("diff", "--name-only", args.base, args.commit).splitlines()
            print("\n".join(sorted(components(files))))
        else:
            compose(args)
    except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
