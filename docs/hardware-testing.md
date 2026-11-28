# Hardware verification

Use an authorized JIDU6111, wired management, local rollback files and [installation precautions](../README.md#install-on-the-router). Record the exact image checksum, firmware source, compiler and radio. Before upgrading, record the installed build and package versions with `make verify-router ROUTER=ADDRESS`. It uses read-only SSH with a known host key.

| Check key | Observations |
| --- | --- |
| `boot` | Device and board, build identity, kernel log, filesystems, configuration preservation, core service startup |
| `reboot` | Repeat boot, inspect warnings and confirm settings and services persist |
| `memory` | MemTotal, MemAvailable, device-tree reservations, slab and unreclaimable slab, process memory, PSI, zram and OOM events |
| `wifi` | 5 GHz association and traffic, 2.4 GHz on dual-band and disabled on WCSS-off, retries, packet loss, throughput and ath11k errors |
| `network` | Ethernet and WAN, WAN6, DHCP, DNS, firewall, configured VLANs, IRQ and packet steering, flow offload, SQM/CAKE, USB WAN and reconnects where configured |
| `packages` | Trusted signed index and APK install, actual kernel ABI and dependency checks, optional service startup and preserved configuration |
| `local_monitoring` | Bundled packages and local service start, LuCI or local telemetry functionality, configuration and data after upgrade. Record installed APK versions separately from the baseline. |
| `recovery` | Previous image, signed feed and backups available offline. Verify image validation and local access. Exercise applicable failsafe or RAM boot under separate hardware authorization. |

Capture results at the beginning and end of the 72-hour observation window and during representative load. Record crashes, OOM, driver warnings, WAN reconnects, service restarts and memory trends. For before-and-after measurements keep clients, channel, traffic direction, link speed, offload and SQM settings, sampling time and workload comparable. Include idle and load RAM, CPU and softirq split, Ethernet and Wi-Fi throughput, loss and retries, SQM throughput and latency, plus WAN6 failures. Combine local observations with sanitized measurements as needed.

For Stable, provide a JSON report with `source_commit` and `variants`. Each of the four entries uses the following format. Replace every example value with observed evidence. The timestamp window must be at least 72 hours.

```json
{
  "source_commit": "FULL_FIRMWARE_SOURCE_SHA",
  "variants": [
    {
      "compiler": "gcc-kernel",
      "radio": "dual-band",
      "image_sha256": "EXACT_IMAGE_SHA256",
      "started_at": "2026-11-20T09:00:00Z",
      "ended_at": "2026-11-23T09:00:00Z",
      "configuration": "Summarize topology and optional services exercised.",
      "workload": "Describe clients, traffic and observation schedule.",
      "observations": "Summarize test outcomes and cite any sanitized measurements.",
      "checks": {
        "boot": "pass", "reboot": "pass", "memory": "pass", "wifi": "pass",
        "network": "pass", "packages": "pass", "local_monitoring": "pass", "recovery": "pass"
      }
    }
  ]
}
```

Optionally include an `installed_monitoring_packages` object reporting the observed package versions. Keep this report public-safe. A missing variant, shorter observation or failed required check keeps the candidate in Beta. Read the optional interfaces and workload notes when judging the scope of the pass. A fresh read-only inventory helps confirm identity. Physical testing establishes the recorded functional and stability results.
