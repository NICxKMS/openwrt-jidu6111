---
id: repo-release-integrity
name: Firmware release integrity
paths:
- sources/feeds.conf
- scripts/firmware_artifacts.py
- scripts/promotion.py
- scripts/release_*.py
- scripts/release-operator.sh
- '**/sha256sums'
- '**/*.manifest'
- '**/*.bin'
- '**/*.apk'
- '**/*.adb'
- '**/*.itb'
- README.md
---

# Release and artifact metadata

- Review inspectable package metadata, target architecture, versions, full kernel ABI, required dependencies, signed repository consistency and provenance. Verify manifest and checksum naming, completeness, duplicates and consistency with release documentation.
- Verify actual hashes/signatures only when artifact bytes, expected trusted hashes/keys and appropriate tools are available. Never claim binary integrity merely from filenames or checksum text. Global filters deliberately exclude opaque binary formats, so use independent release verification for those files.
- Preserve compatibility of sysupgrade image and package repository. Check board identity, upgrade prerequisites, recovery and rollback guidance. Distinguish source revisions from compiled and installed versions.
- Do not publish private signing keys or introduce instructions that disable signature or board validation.
