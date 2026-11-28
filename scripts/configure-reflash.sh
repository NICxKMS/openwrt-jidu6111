#!/usr/bin/env bash
set -euo pipefail

project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project/openwrt"
profile=${1:?Specify gcc-kernel or clang-thinlto}
case "$profile" in
    gcc-kernel|clang-thinlto) ;;
    *) printf 'Unknown build profile %s\n' "$profile" >&2; exit 2;;
esac

radio=${JIDU6111_RADIO:-both}
case "$radio" in
    both) excluded= ;;
    dual-band) excluded=CONFIG_TARGET_DEVICE_qualcommbe_ipq95xx_DEVICE_jiorouter_ax6000-jidu6111-wcss-off ;;
    wcss-off) excluded=CONFIG_TARGET_DEVICE_qualcommbe_ipq95xx_DEVICE_jiorouter_ax6000-jidu6111 ;;
    *) printf 'Unknown radio variant %s\n' "$radio" >&2; exit 2 ;;
esac
output="bin-$profile"
if [[ "$radio" != both ]]; then output="$output-$radio"; fi
if [[ -d build_dir && -f .config ]] && ! grep -Fqx "CONFIG_BINARY_FOLDER=\"$PWD/$output\"" .config; then
    printf '%s\n' 'Use a separate worktree for another compiler or radio build with existing intermediates.' >&2
    exit 1
fi

monitor_pin=$(awk '$2 == "nicx_monitor" { sub(/^.*\^/, "", $3); print $3 }' ../sources/feeds.conf)
if [[ ! "$monitor_pin" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'Invalid Nicx Monitor source pin in sources/feeds.conf.\n' >&2
    exit 1
fi
if [[ ! -d feeds/nicx_monitor ]]; then
    printf 'The Nicx Monitor feed is missing. Run make feeds.\n' >&2
    exit 1
fi
if [[ $(git -C feeds/nicx_monitor rev-parse HEAD 2>/dev/null) != "$monitor_pin" ]]; then
    printf 'The Nicx Monitor feed does not match the source pin. Preserve local edits, move openwrt/feeds/nicx_monitor aside, and run make feeds.\n' >&2
    exit 1
fi
if ! monitor_status=$(git -C feeds/nicx_monitor status --porcelain --untracked-files=all) || [[ -n "$monitor_status" ]]; then
    printf 'The Nicx Monitor feed has local changes or cannot be checked. Preserve local edits and rerun make feeds with a clean checkout.\n' >&2
    exit 1
fi
for package in nicx-telemetry luci-app-nicx-telemetry; do
    source="feeds/nicx_monitor/openwrt/$package"
    destination="package/feeds/nicx_monitor/$package"
    if [[ -e "package/$package" || -L "package/$package" || ! "$source" -ef "$destination" ]]; then
        printf 'Expected %s from the pinned Nicx Monitor feed. Run make feeds in a clean OpenWrt checkout.\n' "$package" >&2
        exit 1
    fi
done

make scripts/config/conf prepare-tmpinfo

seed=$(mktemp .config.reflash-seed.XXXXXX)
resolved=$(mktemp .config.reflash.XXXXXX)
trap 'rm -f "$seed" "$resolved" "$resolved.old"' EXIT

awk -v excluded="$excluded" '
    /^CONFIG_TARGET_qualcommbe_ipq95xx_DEVICE_jiorouter_ax6000-jidu6111=/ { next }
    /^(CONFIG_BINARY_FOLDER=|# CONFIG_BINARY_FOLDER is not set)/ { next }
    /^(CONFIG_|# CONFIG_)/ {
        key = $0
        sub(/^# /, "", key)
        sub(/[= ].*$/, "", key)
        if (key == excluded) next
        if (!(key in settings)) order[++count] = key
        settings[key] = $0
    }
    END { for (i = 1; i <= count; i++) print settings[order[i]] }
' ../config/jidu6111.diffconfig ../config/jidu6111-reflash.diffconfig > "$seed"
if [[ ${JIDU6111_RELEASE_BUILD:-0} == 1 ]]; then
    sed -i -E '/^(# )?CONFIG_(CCACHE|BUILD_LOG)(=| )/d' "$seed"
    printf '%s\n' '# CONFIG_CCACHE is not set' '# CONFIG_BUILD_LOG is not set' >> "$seed"
fi
if [[ "$profile" == clang-thinlto ]]; then
    printf '%s\n' 'CONFIG_KERNEL_LTO_CLANG_THIN=y' >> "$seed"
fi
printf 'CONFIG_BINARY_FOLDER="%s/%s"\n' "$PWD" "$output" >> "$seed"

./scripts/config/conf --defconfig="$seed" -w "$resolved" Config.in
while IFS= read -r setting; do
    if ! grep -Fqx "$setting" "$resolved"; then
        printf 'Could not select %s. Check the source revision and feed dependencies.\n' "$setting" >&2
        exit 1
    fi
done < <(grep -E '^(CONFIG_.+=.+|# CONFIG_.+ is not set)$' "$seed")

if [[ -f .config ]]; then cp -p .config .config.old; fi
mv "$resolved" .config
