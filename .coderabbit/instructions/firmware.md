---
id: repo-firmware
name: OpenWrt board support and patches
paths:
- sources/openwrt.patch
- sources/openwrt/**
- sources/feeds/**
- sources/feeds.conf
- sources/openwrt.commit
- sources/licenses/**
---

# Firmware source and integration

- Review against the pinned OpenWrt and feed revisions and targeted kernel, currently documented as Linux 6.18.60. Verify patch application, ordering, upstream/backport semantics and compatibility after revision changes.
- Inspect embedded changes to DTS/DTSI, kernel config, image recipes and package code in `sources/openwrt.patch` according to their original file types. Check bindings, memory regions, interrupts, clocks, regulators, resets, PHYs, Ethernet and USB initialization.
- Preserve JIDU6111 (qualcommbe/ipq95xx, IPQ9574 and QCN9074) board identifiers, flash partitions, calibration data (ART), image metadata, upgrade validation and recovery. Check other JIDU6J11 variants where shared code changes. Never suggest bypassing image validation to force installation.
- Verify board-data selection, firmware compatibility, provenance and redistribution notices. Opaque board binaries require external extraction/provenance/checksum evidence, not inferred correctness.
- For iwinfo patches, verify IDs, radio mapping and actual reported capabilities used by LuCI and telemetry.
- For feed patches, check package versions/releases, dependency compatibility and runtime behavior. For collectd/RRD, examine lock lifetime, initialization, synchronization, error paths and deadlocks.
- Require evidence for successful boot, hardware behavior, performance and RAM claims. Preserve license notices and applicable redistribution requirements.
