---
id: repo-build-system
name: Firmware build and configuration
paths:
- Makefile
- config/**
- scripts/**
---

# Build wrapper and configuration

- Check pinned source preparation, feed application, patch idempotency, source revision checks, error propagation, incremental builds, dependencies, cache behavior, package index generation and signing.
- Check qualcommbe/ipq95xx and JIDU6111 selection, kernel ABI (including full kernel package version), built-in vs modular package choices, architecture/toolchain compatibility, firmware size and RAM pressure.
- Review interactions between CAKE/SQM, PPE/flow offloading, firewall, VPN, DNS and recovery tools. Do not recommend aggressive flags or extra packages without a demonstrated benefit.
- Preserve signed APK compatibility with the matching firmware. Avoid unintentional removal of recovery and networking capabilities.
- Distinguish host GNU/Bash tooling from router BusyBox ash. Check WSL/Ubuntu paths, quoting, whitespace, working directories, concurrency, partial failures and reproducibility.
- Never unexpectedly delete source changes, worktrees, signing keys, build artifacts or user configuration. Require explicit safeguards for destructive operations.
