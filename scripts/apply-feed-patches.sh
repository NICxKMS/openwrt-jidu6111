#!/usr/bin/env bash
set -euo pipefail

project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
shopt -s nullglob

for patch in "$project"/sources/feeds/*.patch; do
    feed=$(basename -- "$patch" .patch)
    checkout="$project/openwrt/feeds/$feed"

    if [[ ! -d "$checkout" ]]; then
        printf 'Feed %s is missing. Run make feeds first.\n' "$feed" >&2
        exit 1
    fi
    pin=$(awk -v feed="$feed" '$2 == feed { sub(/^.*\^/, "", $3); print $3 }' "$project/sources/feeds.conf")
    if [[ ! $pin =~ ^[0-9a-f]{40}$ || $(git -C "$checkout" rev-parse HEAD) != "$pin" ]]; then
        printf 'Feed %s differs from its source pin. Preserve local changes and rerun make feeds.\n' "$feed" >&2
        exit 1
    fi

    if git -C "$checkout" apply --check "$patch" 2>/dev/null; then
        git -C "$checkout" apply --whitespace=nowarn "$patch"
        printf 'Applied local patches to feed %s.\n' "$feed"
    elif git -C "$checkout" apply --reverse --check "$patch" 2>/dev/null; then
        if git -C "$checkout" diff --quiet HEAD; then
            printf 'Feed %s already contains this patch at its pin. Review %s for retirement.\n' "$feed" "$patch" >&2
        fi
    else
        printf 'Local patch conflicts with feed %s. Review %s before building.\n' "$feed" "$patch" >&2
        exit 1
    fi

    # Also refresh on retries after an interrupted metadata update.
    (cd "$project/openwrt" && ./scripts/feeds update -i "$feed")
done
