# Firmware releases

Use [GitHub Releases](https://github.com/NICxKMS/openwrt-jidu6111/releases) for firmware, matching signed APK feeds, source and toolchain records, verification reports and checksums. Keep every published Stable and Beta artifact and tag immutable. The highest verified Beta version is the active candidate. Lower prereleases remain available for recovery, diagnosis and maintenance. GitHub Latest points to the highest eligible Stable version.

Firmware versions are independent of package versions. Use `vMAJOR.MINOR.PATCH` for Stable and `vMAJOR.MINOR.PATCH-beta.N` for its candidate series, starting at 1. Increment MAJOR for a breaking architecture, installation or device compatibility change, MINOR for a significant kernel, driver or firmware feature change, and PATCH for smaller compatible corrections. Package compatibility depends on the target, architecture, full kernel package version and ABI where required, dependency resolution and APK signing trust.

## Source and GitHub setup

Start task branches and isolated worktrees from `main`, the permanent source branch. Use a merge that retains source ancestry when publishing a maintenance build from an older Stable tag. Forward-port its applicable fixes and retire the temporary worktree after review. Record the task branch purpose and dependencies in its PR.

Before enabling publication, merge the firmware checks and release workflow into `main` and verify its CI run. Then make `main` the GitHub default. Require **Required repository checks** on `main`, prevent forced updates and deletion, and retain immutable GitHub releases. Add a protected `firmware-release` environment restricted to the `main` branch, require the maintainer reviewer, and disable administrator bypass. A solo maintainer can approve their own dispatch. Set the environment variable `JIDU6111_RELEASE_MAINTAINER` to that reviewer's GitHub login. Set the repository variable `JIDU6111_FIRMWARE_KEY_SHA256` to the SHA-256 of the approved public key bytes embedded in the firmware. The workflow also checks the recorded environment approval and uses one publication group. [GitHub environment protection](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments) · [Immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)

Retire temporary source refs only after checking all worktrees, open PRs, reachability and active consumers. Record exact commit IDs for older recoverable baselines. Before retiring the legacy download ref, preserve its tags and provide verified replacement downloads for every still-used image and package feed. Test discovery, checksums and package installation for the supported installed systems. Keep the legacy ref while those checks are pending.

## Build and publish Beta

```sh
make host-deps
make build-firmware COMMIT="$(git rev-parse HEAD)" OUTPUT=/path/to/new-beta-assets \
  SIGNING_KEY=/private/openwrt-signing.pem JOBS=4
make release-beta COMMIT="$(git rev-parse HEAD)" TAG=v1.1.0-beta.1 \
  OUTPUT=/path/to/new-beta-assets NOTES=/path/to/release-notes.md
```

The full build produces two radio images per compiler, one signed feed per compiler after verifying both images have the same kernel and trust, and one build information file per compiler. Use a fresh version tag for changed bytes. Staging reserves the source tag after upload. The tag can be visible before the draft and its assets are published. The operator stages all assets on a draft, then dispatches the workflow from `main`. Review the draft and exact manifest checksum when approving the environment job. GitHub requires push access to read draft releases, so the protected job independently verifies the complete file digests, exact source and pins, image metadata, key trust and APK signatures after approval and before publication. It rechecks the draft asset IDs and digests and checks public downloads before marking the release eligible. If the public download check fails, rerun the workflow for the same asset set and tag. The pending release stays outside normal channel selection.

Write release notes identifying the variant matrix, known issues, installation prerequisites and actual verification. Beta metadata reports built and artifact/feed verified. Any hardware evidence for Beta belongs in its notes with the exact image checksum and test date. The files contain the full source pins, image and feed hashes, resolved configurations, toolchain versions and embedded signing key fingerprint. These inputs aid investigation and rebuilding. Preserve the original release bytes because build environment, signing and timestamps can affect binary reproducibility.

## Promote exact bytes to Stable

1. Select the immutable, verified Beta for the target version. Download its assets to a new local directory and keep the Beta tag and source commit.
2. Complete [hardware verification](hardware-testing.md) on each exact image. Use the full 72-hour window per variant for the current policy. Preserve the previous image and matching feed for recovery. Keep private configuration and telemetry out of the report.
3. Prepare and stage Stable from the separate local directory. The promotion step adds a release descriptor and evidence file. CI compares the rest of the manifest to the immutable Beta, including every image, feed and build record checksum.
4. Review the staged hardware report and exact manifest checksum before approving the protected job. The job repeats artifact and promotion checks before publication. The new Stable tag resolves to the tested source. Publishing a lower maintenance version keeps Latest on the newer Stable.

```sh
gh release download v1.1.0-beta.1 --dir /path/to/local-promotion --pattern '*'
make promote COMMIT=SOURCE_SHA TAG=v1.1.0 BETA=v1.1.0-beta.1 \
  EVIDENCE=/path/to/hardware-evidence.json OUTPUT=/path/to/local-promotion \
  NOTES=/path/to/stable-notes.md
```

A published Stable release requires functional and stability evidence for all four variants. Keep candidates with incomplete hardware coverage in Beta. For an older firmware fix, the temporary maintenance branch starts at its release tag. Publish its fixed bytes under a new patch version and preserve the older release.

## Build storage and scope

Use native Linux storage in WSL2. The release builder keeps one compiled profile at a time and shares downloads only within that build. Interactive builds retain their toolchain and optional compiler cache. Use a separate worktree per compiler or radio build with existing intermediates. For a local configuration check, run `make configure-gcc-kernel BUILD_RADIO=wcss-off` or use `dual-band`. Omit `BUILD_RADIO` for both. `JIDU6111_OPENWRT_REFERENCE` can point to a complete local OpenWrt Git checkout containing the first pinned parent, avoiding a second network fetch of its history.

`make storage-report` shows release scratch use and free space. `REMOTE=1` adds GitHub assets and cache usage. `make cleanup` previews deletion of abandoned, builder-owned scratch directories. Use `APPLY=1` after inspection. Active builds hold locks. Keep private keys and recovery copies outside generated and scratch directories.

| Change | Normal local validation |
| --- | --- |
| Documentation | Repository checks |
| Userspace recipe | Package build, signed index and installation test on a matching target |
| Driver patch | Prepare patched package or kernel, then compile and test affected profiles |
| Device tree or reservation | Affected image, boot and memory/radio functional checks |
| Kernel or compiler | Affected image and kernel-dependent packages, with new ABI and regression checks |
| Feed pin | Prepare all pins, verify package metadata and build affected recipes |

Use `make patch-report` to list patch fingerprints, references and recorded status. For kernel and networking changes, run the manual patch preparation option in Firmware repository checks, or use the same OpenWrt targets locally. Review the downstream overlay and [driver audit](../sources/jidu6111-driver-audit.md) against the actual patched source. Remove an upstream backport only after confirming equivalence at the selected pin and checking application order and regressions.
