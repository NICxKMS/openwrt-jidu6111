#!/usr/bin/env bash
set -euo pipefail

project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
destination="$project/openwrt"
sources="$project/sources"

if [[ -d "$destination/.git" ]]; then
    printf 'OpenWrt checkout already exists at %s\n' "$destination"
    exit 0
fi

if [[ -e "$destination" || -L "$destination" ]]; then
    printf 'The OpenWrt destination already exists at %s\n' "$destination" >&2
    exit 1
fi

read -r -a parents <<<"$(awk '$1 == "parent" { print $2 }' "$sources/openwrt.commit" | paste -sd ' ' -)"
expected_tree=$(awk '$1 == "tree" { print $2; exit }' "$sources/openwrt.commit")
if [[ ${#parents[@]} != 2 || -z "$expected_tree" ]]; then
    echo 'Expected a pinned OpenWrt merge with two parents.' >&2
    exit 1
fi

checkout=$(mktemp -d "$project/.openwrt-source.XXXXXX")
trap 'rm -rf -- "$checkout"' EXIT
git -C "$checkout" init --quiet
git -C "$checkout" remote add origin https://github.com/openwrt/openwrt.git
git -C "$checkout" fetch --no-tags origin "${parents[0]}"
git -C "$checkout" fetch --no-tags https://github.com/SahilB69/openwrt.git "${parents[1]}"
git -C "$checkout" switch --quiet --detach "${parents[0]}"
git -C "$checkout" -c user.name='OpenWrt Source Bootstrap' -c user.email='openwrt-build@localhost' \
    merge --no-edit --no-commit --no-ff "${parents[1]}"

if [[ $(git -C "$checkout" write-tree) != "$expected_tree" ]]; then
    echo 'The merged OpenWrt sources differ from the pinned tree.' >&2
    exit 1
fi

commit=$(git -C "$checkout" hash-object -t commit -w --stdin <"$sources/openwrt.commit")
git -C "$checkout" reset --hard "$commit"
git -C "$checkout" apply "$sources/openwrt.patch"
cp -R "$sources/openwrt/." "$checkout/"
cp "$sources/feeds.conf" "$checkout/feeds.conf"
mv -nT -- "$checkout" "$destination"
if [[ -d "$checkout" ]]; then
    printf 'The OpenWrt destination appeared during setup at %s\n' "$destination" >&2
    exit 1
fi

printf 'OpenWrt source is ready at %s\n' "$destination"
