# AGENTS.md — `.github/`

CI, Dependabot, and pull-request templates. Parent: [../AGENTS.md](../AGENTS.md).

## Layout

| Path | Role |
| --- | --- |
| [`workflows/ci.yml`](workflows/ci.yml) | PR/main gates: Ruff, unittest + coverage, PR diff-cover ≥75%, frontend lint + build |
| [`PULL_REQUEST_TEMPLATE.md`](PULL_REQUEST_TEMPLATE.md) | Required PR body sections for agents and humans |
| [`dependabot.yml`](dependabot.yml) | Weekly GitHub Actions, uv, and frontend npm updates |

## Conventions

- Inherit root [AGENTS.md](../AGENTS.md): minimal comments; update this file when CI jobs, ecosystems, or the PR template sections change.
- CI must not need provider API keys, LDView, or LPub3D.
- Python tests run under `coverage`. On pull_request, `diff-cover` requires ≥75%
  coverage of changed lines under `src/legolizer/` (root AGENTS rule 6).
- Keep the PR template sections stable; agents fill every heading (use `none` when empty).
- Do not commit `TASKS.md` from workflows or templates.

## Agent backlog

- #50 — Add frontend test suite and CI job (filed 2026-09-26) — see src/frontend/AGENTS.md
- #22 — Require CI status checks on main (filed 2026-09-26)
