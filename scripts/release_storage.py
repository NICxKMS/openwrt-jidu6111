"""Report storage and reap abandoned firmware workspaces."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


from release_workflow import GitHub, REPO


def build_root():
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return Path(os.environ.get("JIDU6111_BUILD_ROOT") or state / "jidu6111/builds").resolve()


def cleanup(root, *, apply):
    if not root.is_dir() or root.is_symlink():
        return []
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_info = os.fstat(root_fd)
        if root_info.st_uid != os.getuid() or root_info.st_mode & 0o077:
            raise ValueError("Build workspace root must be private and owned by your account (chmod 700)")
        return clean_private_root(root, root_fd, apply=apply)
    finally:
        os.close(root_fd)


def clean_private_root(root, root_fd, *, apply):
    candidates = []
    for name in sorted(os.listdir(root_fd)):
        if not re.fullmatch(r"build\.[A-Za-z0-9_]{8}", name):
            continue
        try:
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        except (FileNotFoundError, NotADirectoryError):
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or not os.path.samestat(
                info, os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            ):
                continue
            marker = os.stat(".jidu6111-owned", dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(marker.st_mode) or marker.st_uid != os.getuid():
                continue
            if apply:
                shutil.rmtree(Path(f"/proc/self/fd/{root_fd}") / name)
            candidates.append(root / name)
        except (BlockingIOError, FileNotFoundError):
            continue
        finally:
            os.close(fd)
    return candidates


def report(root, remote):
    anchor = next(path for path in (root, *root.parents) if path.is_dir())
    disk = shutil.disk_usage(anchor)
    print(f"Build filesystem free: {disk.free:,} bytes")
    if root.is_dir():
        subprocess.run(["du", "-sh", "--", str(root)], check=True)
    if remote:
        github = GitHub(REPO)
        caches = [cache for page in github.api("actions/caches", paginate=True) for cache in page["actions_caches"]]
        print(f"GitHub Actions caches: {len(caches)} using {sum(cache['size_in_bytes'] for cache in caches):,} bytes")
        print(json.dumps([
            {"tag": release["tag_name"], "draft": release["draft"],
             "bytes": sum(asset["size"] for asset in release["assets"])}
            for release in github.releases()
        ], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("report", "cleanup"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--remote", action="store_true")
    args = parser.parse_args()
    try:
        if args.operation == "report":
            report(build_root().absolute(), args.remote)
        else:
            for path in cleanup(build_root(), apply=args.apply):
                print(("Removed" if args.apply else "Would remove") + f" {path}")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
