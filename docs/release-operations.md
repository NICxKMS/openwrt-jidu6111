# Release operations

GitHub Releases is the distribution and version record. Keep the verified Stable release marked Latest and one verified Development prerelease when a distinct candidate exists. A release contains the sysupgrade images, signed feeds by compatibility profile, provenance, and verification status. Treat a managed draft as active work. Retire superseded release entries after the replacement downloads have been verified, retaining their source tags.

## Source branches and prerequisites

| Branch | Purpose | Lifecycle |
| --- | --- | --- |
| `development` | Integrated firmware and monitoring, default development branch | Permanent |
| `stable` | Production source and approved promotions | Permanent |
| `codex/jidu6111-release-workflow` | Introduce the release and promotion workflows | Retire after the reviewed workflow lands |
| `router` | Existing signed feed and legacy downloads | Retire after the hardware cutover and branch approval |
| `main` | Previous default and migration base | Retire after default-branch cutover and reference audit |
| `codex/<component>` | Scoped work in its own worktree | Retire after merge, verification and worktree cleanup |

Start ordinary work from `development`. Give each task a worktree and record its purpose, dependencies and retirement condition in the PR. Target `development` for normal changes, and `stable` for reviewed selective promotion or emergency fixes. Integrate emergency fixes back into `development`.

Before activating these workflows, enable immutable releases, protect both source branches with the **Required repository checks** job, and update the default branch after the new checks are present. Set the `production` environment to allow only `stable`. Give the maintainer sole reviewer authority and set `JIDU6111_PRODUCTION_MAINTAINER` to the GitHub login that may approve jobs. For a single maintainer, allow them to approve their own dispatch and disable admin bypass. Scope the Cloudflare account ID and deploy token to that environment. Restrict `development-release` to `development`. Audit existing Cloudflare deployment paths and switch them over only with production approval.

## Development build and publication

Run local firmware builds on a filesystem with capacity for a clean OpenWrt build. Use an exact checked-out commit and a private APK signing key outside source control. The build verifies the firmware, embedded key, kernel package version, signed index and feed. It produces GCC and Clang ThinLTO with dual-band and WCSS-off images unless you request one compiler using `BUILD_PROFILE` for a local check. A published Development release includes both profiles.

```sh
make host-deps
make build-firmware COMMIT="$(git rev-parse HEAD)" OUTPUT=/path/to/new-assets \
  SIGNING_KEY=/private/openwrt-signing.pem JOBS=4
make test-release
make release-dev COMMIT="$(git rev-parse HEAD)" TAG=v1.0.1-dev.1.1 OUTPUT=/path/to/new-assets
```

Use a unique versioned tag for every candidate. The Development workflow requires the protected Development head, repeats integrated checks, independently verifies the signed release assets, and checks public downloads after publishing. If verification fails, the previous release remains ready. Fix and retry the same draft when its staged bytes are unchanged, or use a new tag for different bytes. After a verified upload you can discard the dedicated local asset directory when you have finished with it.

For a selective change, inspect the scope with `python3 -B scripts/release_composition.py scope --base OLD_SHA --commit NEW_SHA`. When firmware and packages are unchanged, fetch the previous verified release using `scripts/release_workflow.py fetch` and run `scripts/release_composition.py compose` for the new source revision. This preserves the actual firmware source pins, and the staged release reuses the verified image and feed by SHA-256. For a userspace package, use the OpenWrt package targets with the compatible source, feed pins, resolved configuration and original signing key. Rebuild or reflash only when dependencies or the kernel ABI require it. Where the original build environment cannot be recovered, keep the original signed files and report the reproducibility gap.

## Stable baseline and promotion

1. Run `make verify-router ROUTER=ADDRESS` with authorized read-only SSH credentials. Confirm the installed firmware, full kernel package version, board, monitoring APKs and key fingerprints. Read the active Cloudflare Worker version and the applied Supabase migration identifiers. Preserve the original signed feed and privately back up configuration, signing keys and monitoring history.
2. To bootstrap, export the current legacy image and signed feed into a disposable directory. Package those exact bytes with `scripts/firmware_artifacts.py bootstrap --help`. Check the original image and APKs against the firmware and package source pins in the legacy README. Mark any unresolved provenance explicitly. Supply verified observed component pins and a promotion descriptor with `kind` set to `bootstrap`. Use the bootstrap operation to publish metadata and existing assets only.
3. For a change, prepare a selective promotion PR. For a firmware promotion use the exact Development image and feed. For a userspace package stage an APK signed for the installed build before installing it. For a dashboard or API change package the production-target dashboard and Worker once with `scripts/monitor-bundle.py build` in [openwrt-router-monitor](https://github.com/NICxKMS/openwrt-router-monitor) and test those artifacts. Use `scripts/release_composition.py compose --help` to attach the promotion descriptor, observed component pins and, where applicable, the verified Worker bundle.
4. After the reviewed source is on `stable`, run `make reserve-stable COMMIT=SHA TAG=v1.0.0`. Wait for its GitHub run, then run `make stage-stable COMMIT=SHA TAG=v1.0.0 OUTPUT=/path/to/assets`. Record the exact manifest and tag with `scripts/promotion.py prepare`. A managed Stable reservation pauses Development publication until the promotion is resolved.
5. Apply only the approved operations. For coupled changes, record the verified package version and accepted telemetry with `python3 -B scripts/promotion.py record-agent --version VERSION --installed-at UTC --received-at UTC` before a dependent Worker rollout. Production workflow definitions live in openwrt-router-monitor and are disabled during migration. Complete the cross-repository approval, draft access and deployment receipt checks before dispatching from the new repository. The existing Stable procedure and evidence remain in the historical firmware revision.
6. Perform approved database operations against the reviewed live migration baseline. Match hosted IDs to repository SQL, rehearse with representative data, back up privately, and apply only the pending approved migrations. Verify permissions and ingestion with the installed agent and the candidate. Keep schema removals in separately approved changes after dependent components have moved.
7. For an approved flash, connect by Ethernet, verify the image hash, run `sysupgrade -T` and preserve the previous Stable image and feed. Back up the settings, package list, credentials and actual vnStat, nlbwmon and collectd/RRD locations. Check reboot, WAN and USB WAN where configured, DNS/DHCP, the selected radios, signed package installation and telemetry. Use the 72-hour observation period for kernel, driver or memory changes. Track untested variants separately.
8. Record the observed results privately using `scripts/promotion.py verify-production`. Its `--help` and validation identify the required fields. Run `make promote COMMIT=SHA TAG=v1.0.0 OUTPUT=/path/to/assets` and approve the publication job. Pass `CONSUME_DEVELOPMENT=TAG` when fully promoting that Development release. After the new downloads are verified and the run succeeds, finalize the owner-only state with `python3 -B scripts/promotion.py complete --manifest /path/to/assets/release-manifest.json --reservation-tag v1.0.0`. Keep the previous Stable available until confirmation.

If a step fails, reconcile actual router, Worker and database state with the operator record before retrying. The previous Stable remains the published recovery point until verification. For an approved recovery, reinstall the previous matching signed package or image, or activate the previous compatible Cloudflare version. Treat database recovery independently and prefer a corrective migration or tested restoration. Restore monitoring history and check telemetry. Once live state is reconciled, cancel the local reservation and remove only the matching unfinished managed GitHub release. Cloudflare maintains its own Worker version history.

## Cleanup and reporting

Use `make cleanup` to preview abandoned owned build directories and `make cleanup APPLY=1` to remove them. Active directory locks protect running builds. The command covers marked release-build workspaces. Inspect historical worktrees, old package bundles and signing files separately before any cleanup. Run `make storage-report` for local storage and add `REMOTE=1` to include GitHub release and Actions cache usage. GitHub-hosted jobs use disposable dependencies. After the new workflows land, remove obsolete repository caches and compare GitHub totals before and after.

Verify the legacy replacement on the physical router before requesting retirement of the old artifact branch and beta tag. Keep raw legacy feed URLs usable during that transition.

## Cloudflare Development Preview

The [standalone monitor repository](https://github.com/NICxKMS/openwrt-router-monitor/blob/main/docs/migration-provenance.md) owns the native Cloudflare Development Preview and its separate Supabase test project. Run the Preview workflow there from its protected `main` branch. Firmware releases and pinned package feed updates do not refresh the dashboard or API.
