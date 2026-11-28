import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}")


def verify_inputs(report: bool) -> None:
    sources = ROOT / "sources"
    pins = [line.split() for line in (sources / "feeds.conf").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    if (any(len(pin) != 3 or pin[0] != "src-git"
            or not re.fullmatch(r"https://[^\s^]+\^[0-9a-f]{40}", pin[2]) for pin in pins)
            or len({pin[1] for pin in pins}) != len(pins)
            or not any(pin[1] == "nicx_monitor" and
                       pin[2].startswith("https://github.com/NICxKMS/openwrt-router-monitor.git^") for pin in pins)):
        raise ValueError("Expected unique feed names and exact HTTPS Git commit pins")
    header = (sources / "openwrt.commit").read_text().split("\n\n", 1)[0].splitlines()
    for key, count in (("tree", 1), ("parent", 2)):
        revisions = [line.split()[1] for line in header if line.startswith(key + " ")]
        if len(set(revisions)) != count or not all(SHA.fullmatch(rev) for rev in revisions):
            raise ValueError(f"Expected {count} immutable OpenWrt {key} revisions")

    rows = json.loads((sources / "patches.json").read_text())
    inventory = {row["id"]: row for row in rows}
    actual = {str(path.relative_to(ROOT)) for path in sources.rglob("*.patch")}
    if len(inventory) != len(rows) or actual != {row["path"] for row in rows} or len(actual) != len(rows):
        raise ValueError("The patch inventory and local files must correspond one-to-one")
    patch_ids = set()
    for row in rows:
        path = ROOT / row["path"]
        contents = path.read_bytes()
        dependencies = row.get("depends_on", [])
        if any(dep not in inventory or (ROOT / inventory[dep]["path"]).parent != path.parent
               or inventory[dep]["path"] >= row["path"] for dep in dependencies):
            raise ValueError(f"Invalid patch dependency or application order for {row['id']}")
        if row.get("patch_header_commit") and not contents.startswith(
            b"From " + row["patch_header_commit"].encode() + b" "
        ):
            raise ValueError(f"Patch provenance differs from its header for {row['id']}")
        paths = subprocess.check_output(["git", "apply", "--numstat", "--whitespace=nowarn", "-"], input=contents)
        first = re.search(rb"(?m)^--- (?:a/|/dev/null)", contents)
        if not paths or first is None:
            raise ValueError(f"Missing unified diff for {row['id']}")
        changes = re.findall(rb"(?m)^[-+].*", contents[first.start():])
        identity = hashlib.sha256(re.sub(rb"[ \t]", b"", b"\n".join(changes))).digest()
        if identity in patch_ids:
            raise ValueError(f"Duplicate patch content for {row['id']}")
        patch_ids.add(identity)
        if report:
            print(f"{row['id']} {hashlib.sha256(contents).hexdigest()} {row['upstream_status']}"
                  f" | {row.get('reference', 'see patch header and driver audit')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate firmware pins and the downstream patch inventory.")
    parser.add_argument("--report", action="store_true")
    try:
        verify_inputs(parser.parse_args().report)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
