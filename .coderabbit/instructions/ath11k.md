---
id: repo-ath11k
name: Qualcomm wireless driver review
paths:
- sources/openwrt/package/kernel/mac80211/patches/ath11k/**
- sources/openwrt.patch
---

# ath11k changes (where relevant)

- Inspect IRQ control idempotency, locking, interrupt context, DMA map/unmap, buffer ownership, RXDMA page-fragment caches, monitor ring sizes, descriptors and allocation failure unwinding.
- Verify partial initialization, ring teardown, firmware crash/recovery, interface restart, radio disable, use-after-free, double-free, leaks and races. Verify backport behavior against the pinned kernel/firmware interfaces.
- Account for both IPQ9574 and QCN9074 and the JIDU6111's 512 MB physical RAM. Distinguish firmware/WCSS reserved regions, DMA buffers, reclaimable and unreclaimable slab, page caches, tmpfs and userspace RSS.
- Do not assume disabling a radio reclaims reserved memory without actual allocation and teardown evidence. Do not assign all observed RAM differences to ath11k.
- Check memory savings against throughput, packet loss, monitor operation, wireless stability and recovery; require comparable actual-router measurements for claims of improvement.
