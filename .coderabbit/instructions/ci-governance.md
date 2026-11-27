---
id: repo-ci-governance
name: CI and repository governance
paths:
- .github/**
- .coderabbit.yaml
- .coderabbit/**
- README.md
---

# CI and governance

- Check GitHub Actions triggers, permissions, secret boundaries, untrusted PR execution, dependency pinning, caching, concurrency, artifacts and failure propagation. Prevent unauthorized production deployment or privileged execution from untrusted contributions.
- Verify firmware working directories and path filters in `.github/workflows/firmware-checks.yml`. Check that the pinned monitor feed resolves both recipes and required statuses propagate failures.
- Review app CI and deploy policy in NICxKMS/openwrt-router-monitor. Coordinate production sequencing across the repositories.
- Validate CODEOWNERS, PR templates, dependabot paths and review ownership. Respect parallel worktrees and avoid unnecessary automatic changes or merges.
- Validate CodeRabbit settings and instruction front matter against current documented rules. Keep all target branches covered; check accidental exclusions, duplicate IDs, wrong relative paths and overlapping contradictory instructions.
- Check installation, prerequisites, compatibility, recovery and documentation claims against actual implementation. Do not invent tests or deployment evidence.
