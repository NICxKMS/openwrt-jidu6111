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
- Verify working directories and path filters for firmware and the nested pnpm workspace. Avoid duplicate builds or treating skipped jobs as successful verification.
- For `.github/workflows/nicx-router-monitor.yml`, review the nested pnpm workspace, browser-safe build values, required checks and manual production deployment. Compare with the standalone workflow template and `nicx-router-monitor/docs/deployment.md` for migration and rollout ordering.
- Validate CODEOWNERS, PR templates, dependabot paths and review ownership. Respect parallel worktrees and avoid unnecessary automatic changes or merges.
- Validate CodeRabbit settings and instruction front matter against current documented rules. Keep all target branches covered; check accidental exclusions, duplicate IDs, wrong relative paths and overlapping contradictory instructions.
- Check installation, prerequisites, compatibility, recovery and documentation claims against actual implementation. Do not invent tests or deployment evidence.
