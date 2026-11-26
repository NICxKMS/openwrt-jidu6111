#!/usr/bin/env bash
set -euo pipefail

project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project/openwrt"
flavor=${1:-optimized}
case "$flavor" in
    optimized|thinlto) ;;
    *) printf 'Unknown build profile %s\n' "$flavor" >&2; exit 2;;
esac

for package in nicx-telemetry luci-app-nicx-telemetry; do
    source="$project/nicx-router-monitor/openwrt/$package"
    destination="package/$package"
    if [[ ! -e "$destination" && ! -L "$destination" ]]; then
        ln -s "$source" "$destination"
    fi
    if [[ ! "$source" -ef "$destination" ]]; then
        printf 'Unexpected existing package at %s\n' "$destination" >&2
        exit 1
    fi
done

make scripts/config/conf prepare-tmpinfo

seed=$(mktemp .config.optimized-seed.XXXXXX)
resolved=$(mktemp .config.optimized.XXXXXX)
trap 'rm -f "$seed" "$resolved" "$resolved.old"' EXIT

awk '
    /^CONFIG_TARGET_qualcommbe_ipq95xx_DEVICE_jiorouter_ax6000-jidu6111=/ { next }
    /^(CONFIG_|# CONFIG_)/ {
        key = $0
        sub(/^# /, "", key)
        sub(/[= ].*$/, "", key)
        if (!(key in settings)) order[++count] = key
        settings[key] = $0
    }
    END { for (i = 1; i <= count; i++) print settings[order[i]] }
' ../config/jidu6111.diffconfig ../config/jidu6111-optimized.diffconfig > "$seed"
if [[ "$flavor" == thinlto ]]; then
    printf '%s\n' 'CONFIG_KERNEL_LTO_CLANG_THIN=y' >> "$seed"
fi
printf 'CONFIG_BINARY_FOLDER="%s/bin-%s"\n' "$PWD" "$flavor" >> "$seed"

./scripts/config/conf --defconfig="$seed" -w "$resolved" Config.in
while IFS= read -r setting; do
    if ! grep -Fqx "$setting" "$resolved"; then
        printf 'Could not select %s. Check the source revision and feed dependencies.\n' "$setting" >&2
        exit 1
    fi
done < <(grep -E '^(CONFIG_.+=.+|# CONFIG_.+ is not set)$' "$seed")

if [[ -f .config ]]; then cp -p .config .config.old; fi
mv "$resolved" .config
