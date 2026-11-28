#!/usr/bin/env bash
set -euo pipefail

operation=${1:-}
repo=NICxKMS/openwrt-jidu6111
tag=${JIDU_OP_TAG:?Set TAG to a new firmware version}
commit=${JIDU_OP_COMMIT:?Set COMMIT to the exact firmware source revision}
output=${JIDU_OP_OUTPUT:?Set OUTPUT to the verified release asset directory}
manifest="$output/release-manifest.json"

default_branch=$(gh api "repos/$repo" --jq .default_branch)
[[ $default_branch == main ]] || { echo 'Release publication requires main as the default branch.' >&2; exit 1; }
main=$(gh api "repos/$repo/git/ref/heads/main" --jq .object.sha)
[[ $commit =~ ^[0-9a-f]{40}$ ]] || exit 2
git merge-base --is-ancestor "$commit" "$main" || {
    echo 'Source must be reachable from the current origin/main. Fetch and verify the release source.' >&2
    exit 1
}
case "$operation" in
    beta) channel=beta ;;
    stable)
        channel=stable
        if [[ ! -f "$output/hardware-evidence.json" ]]; then
            python3 -B scripts/promotion.py prepare --commit "$commit" --tag "$tag" \
                --beta "${JIDU_OP_BETA:?Set BETA to the verified Beta tag}" \
                --evidence "${JIDU_OP_EVIDENCE:?Set EVIDENCE to the hardware report}" --directory "$output"
        fi
        ;;
    *) printf '%s\n' 'Choose beta or stable.' >&2; exit 2 ;;
esac

python3 -B scripts/release_workflow.py stage --channel "$channel" --tag "$tag" --commit "$commit" \
    --directory "$output" ${JIDU_OP_NOTES:+--notes-file "$JIDU_OP_NOTES"}
digest=$(sha256sum "$manifest" | cut -d ' ' -f1)
gh workflow run firmware-release.yml --repo "$repo" --ref main \
    -f "channel=$channel" -f "source_commit=$commit" -f "tag=$tag" -f "manifest_sha=$digest"
