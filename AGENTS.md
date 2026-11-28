# JIDU6111 firmware development

- Start new work from `main` and older release fixes from the matching immutable tag. Use temporary branches and isolated worktrees. Record branch purpose, dependencies and retirement condition in the PR. Preserve other worktrees and local edits.
- Stable and Beta are GitHub release channels. Keep published tags and assets immutable. Retain previous verified images and matching signed feeds.
- Pin OpenWrt and feeds to full Git commits. Build the monitoring APKs from `nicx_monitor`. Own the baseline package selection and signed firmware feed here. Keep package development and hosted monitoring operations in their owning project.
- Review kernel, driver and DTS changes against the pinned source, local patch order, calibration data and recovery path. Update the patch inventory. Keep changes to performance behavior independently reviewable.
- Treat the board, target, architecture, full kernel package version, ABI, build profile and APK trust as release compatibility inputs. Keep signing private keys outside the tree and build output.
- Preserve both compiler profiles and both radio options. Use `make test-release`, `make patch-report` and scoped preparation or build checks. Record precisely which checks ran and which artifacts or variants they covered.
- Physical router access and changes require authorization. Preserve configuration, calibration, statistics and recovery copies. Stable requires observed hardware evidence and maintainer approval. CI and fixtures are host verification.
