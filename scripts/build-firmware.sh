#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: scripts/build-firmware.sh --commit FULL_SHA --output NEW_DIR --signing-key FILE' \
        '       [--profile gcc-kernel|clang-thinlto] [--jobs N]' \
        'JIDU6111_BUILD_ROOT controls the disposable workspaces. Choose an output on the same disk.' \
        'Set KERNEL_LLVM to a tool suffix such as -21 or a tool directory ending in / when needed.'
}

fail() { printf '%s\n' "$*" >&2; exit 1; }

# OpenWrt rejects PATH entries it cannot safely split. Apply this to direct script calls as well.
PATH=$(printf '%s' "$PATH" | command -p awk -v RS=: '/^\// && !/[[:space:]]/ { printf "%s%s", separator, $0; separator = ":" }')
export PATH

project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
commit= output= key= profile= jobs=4
while (( $# )); do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --commit|--output|--signing-key|--profile|--jobs)
            (( $# >= 2 )) || fail "Missing value for $1"
            case "$1" in
                --commit) commit=$2 ;;
                --output) output=$2 ;;
                --signing-key) key=$2 ;;
                --profile) profile=$2 ;;
                --jobs) jobs=$2 ;;
            esac
            shift 2 ;;
        *) fail "Unknown build argument: $1" ;;
    esac
done

[[ $commit =~ ^[a-f0-9]{40}$ && -n $output && -n $key ]] || { usage >&2; exit 2; }
[[ $jobs =~ ^[1-9][0-9]{0,2}$ ]] || fail 'Build jobs must be a positive integer up to 999.'
case "$profile" in
    '') profiles=(gcc-kernel clang-thinlto) ;;
    gcc-kernel|clang-thinlto) profiles=("$profile") ;;
    *) fail "Unknown build profile: $profile" ;;
esac
[[ ! -e $output && ! -L $output ]] || fail "Output already exists: $output"
output_parent=$(realpath -e -- "$(dirname -- "$output")")
output="$output_parent/$(basename -- "$output")"
[[ -f $key ]] || fail 'Select an existing APK signing private key.'
key=$(realpath -e -- "$key")
[[ $(git -C "$project" rev-parse --verify "$commit^{commit}") == "$commit" ]] || fail 'Select an exact local Git commit.'

for tool in awk flock git make openssl python3 unsquashfs; do
    command -v "$tool" >/dev/null || fail "Missing build dependency: $tool"
done
llvm_prefix= llvm_suffix=
if [[ ! $profile || $profile == clang-thinlto ]]; then
    export KERNEL_LLVM=${KERNEL_LLVM:-1}
    if [[ $KERNEL_LLVM =~ ^-[0-9]+$ ]]; then
        llvm_suffix=$KERNEL_LLVM
    elif [[ $KERNEL_LLVM == /*/ && $KERNEL_LLVM != *[[:space:]]* ]]; then
        llvm_prefix=$KERNEL_LLVM
    elif [[ $KERNEL_LLVM != 1 ]]; then
        fail 'KERNEL_LLVM must be 1, a tool suffix such as -21, or a tool directory ending in /.'
    fi
    for tool in clang ld.lld llvm-ar llvm-nm llvm-objcopy llvm-objdump llvm-readelf llvm-strip; do
        executable="$llvm_prefix$tool$llvm_suffix"
        command -v "$executable" >/dev/null || fail "Missing Clang ThinLTO dependency: $executable"
    done
fi

scratch=${JIDU6111_BUILD_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/jidu6111/builds}
mkdir -p -m 700 -- "$scratch"
scratch=$(realpath -e -- "$scratch")
[[ -O $scratch ]] || fail 'Use a build workspace owned by your account.'
[[ $scratch != *[[:space:]]* ]] || fail 'OpenWrt requires a build workspace path without whitespace.'
[[ $scratch != *\'* && $scratch != *\^* && $scratch != *\;* ]] || fail 'Choose a build workspace path without quotes, carets or semicolons.'
[[ $(stat -c %d -- "$scratch") == "$(stat -c %d -- "$output_parent")" ]] \
    || fail 'The build workspace and output must be on the same filesystem.'

JIDU6111_BUILD_ROOT="$scratch" python3 -B "$project/scripts/release_storage.py" cleanup --apply
workspace=$(mktemp -d "$scratch/build.XXXXXXXX")
exec {workspace_lock}<"$workspace"
flock -xn "$workspace_lock"
trap 'rm -rf -- "$workspace"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
: > "$workspace/.jidu6111-owned"
mkdir -p -- "$workspace/artifacts" "$workspace/tmp" "$workspace/cache" "$workspace/downloads"
export TMPDIR="$workspace/tmp" XDG_CACHE_HOME="$workspace/cache" CCACHE_DISABLE=1
export JIDU6111_RELEASE_BUILD=1

source="$workspace/source"
git clone --quiet --shared --no-checkout "$project" "$source"
git -C "$source" switch --quiet --detach "$commit"
[[ -z $(git -C "$source" status --porcelain) ]] || fail 'The selected source checkout is dirty.'

collector="$project/scripts/firmware_artifacts.py"
openwrt="$source/openwrt"
make -C "$source" source feeds
# Fetch the pinned OpenWrt source and feeds once. Each compiler gets its own clean copy.
if (( ${#profiles[@]} > 1 )); then
    mv -- "$openwrt" "$workspace/pinned-source"
fi
manifest_args=()
for current_profile in "${profiles[@]}"; do
    started=$SECONDS
    if [[ -d $workspace/pinned-source ]]; then
        cp -a --reflink=auto -- "$workspace/pinned-source" "$openwrt"
    fi
    # The directory survives compiler-profile cleanup, and the workspace trap removes it.
    ln -s -- "$workspace/downloads" "$openwrt/dl"
    openssl pkey -in "$key" -passin pass: -pubout -out "$openwrt/public-key.pem"
    ln -s -- "$key" "$openwrt/private-key.pem"
    make -C "$source" "configure-$current_profile"
    for required in CONFIG_USE_APK=y CONFIG_SIGNED_PACKAGES=y CONFIG_SIGN_EACH_PACKAGE=y; do
        grep -Fqx -- "$required" "$openwrt/.config" || fail "Required APK setting missing: $required"
    done
    if grep -Eq '^CONFIG_(CCACHE|BUILD_LOG)=y$' "$openwrt/.config"; then
        fail 'The selected source enables a compiler cache or per-package log files.'
    fi
    make -C "$openwrt" -j"$jobs"
    make -C "$openwrt" package/index package/merge-index

    tool_args=()
    tools=(gcc ld)
    if [[ $current_profile == clang-thinlto ]]; then
        tools+=("${llvm_prefix}clang${llvm_suffix}" "${llvm_prefix}ld.lld${llvm_suffix}")
    fi
    for tool in "${tools[@]}"; do
        version=$("$tool" --version)
        tool_args+=(--tool-version "${tool##*/}" "${version%%$'\n'*}")
    done
    shopt -s nullglob
    for tool in "$openwrt"/staging_dir/toolchain-*/bin/aarch64-openwrt-linux-musl-{gcc,ld}; do
        version=$("$tool" --version)
        tool_args+=(--tool-version "${tool##*/}" "${version%%$'\n'*}")
    done
    shopt -u nullglob
    record="$workspace/$current_profile.json"
    python3 -B "$collector" collect --openwrt "$openwrt" --output "$workspace/artifacts" \
        --profile "$current_profile" --commit "$commit" --profile-record "$record" "${tool_args[@]}"
    manifest_args+=(--profile-record "$record")
    printf 'Verified %s in %s seconds. Workspace usage before cleanup ' "$current_profile" "$(( SECONDS - started ))"
    du -sh -- "$workspace" | cut -f1
    rm -rf -- "$openwrt"
done

python3 -B "$collector" manifest --output "$workspace/artifacts" --commit "$commit" "${manifest_args[@]}"
mv -nT -- "$workspace/artifacts" "$output"
[[ ! -d $workspace/artifacts ]] || fail "Output appeared while building: $output"
printf 'Verified build assets are ready at %s\n' "$output"
