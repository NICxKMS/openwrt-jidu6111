#!/usr/bin/env bash
set -euo pipefail

operation=${1:-}
case "$operation" in
    development|reserve|stage|promote) ;;
    *) printf 'Choose development, reserve, stage or promote.
' >&2; exit 2 ;;
esac

repo=NICxKMS/openwrt-jidu6111
tag=${JIDU_OP_TAG:?Set TAG to the unique version tag}
commit=${JIDU_OP_COMMIT:?Set COMMIT to the exact verified source revision}
root=(python3 -B scripts/release_workflow.py --repo "$repo")
stable=(--channel stable --tag "$tag" --commit "$commit")
output=${JIDU_OP_OUTPUT:-}
manifest="$output/release-manifest.json"

case "$operation" in
    development)
        : "${output:?Set OUTPUT to the verified release asset directory}"
        python3 -B scripts/release_composition.py compose --commit "$commit" --directory "$output"
        digest=$(sha256sum "$manifest" | cut -d ' ' -f1)
        "${root[@]}" stage --channel development --tag "$tag" --commit "$commit" --directory "$output"
        gh workflow run firmware-release.yml --repo "$repo" --ref development \
            -f channel=development -f "source_commit=$commit" -f "tag=$tag" -f "manifest_sha=$digest"
        ;;
    reserve)
        [[ "$(gh api "repos/$repo/git/ref/heads/stable" --jq .object.sha)" == "$commit" ]]
        gh workflow run firmware-release.yml --repo "$repo" --ref stable \
            -f operation=reserve -f channel=stable -f "source_commit=$commit" -f "tag=$tag"
        ;;
    stage)
        : "${output:?Set OUTPUT to the verified Stable asset directory}"
        "${root[@]}" stage "${stable[@]}" --directory "$output"
        ;;
    promote)
        : "${output:?Set OUTPUT to the verified Stable asset directory}"
        evidence=$(python3 -B scripts/promotion.py publication-evidence --manifest "$manifest" --reservation-tag "$tag")
        digest=$(sha256sum "$manifest" | cut -d ' ' -f1)
        args=()
        if [[ -n ${JIDU_OP_CONSUME:-} ]]; then
            args+=(-f "consume_development=$JIDU_OP_CONSUME")
        fi
        gh workflow run firmware-release.yml --repo "$repo" --ref stable \
            -f channel=stable -f "source_commit=$commit" -f "tag=$tag" -f "manifest_sha=$digest" -f "production_evidence=$evidence" "${args[@]}"
        ;;
esac
