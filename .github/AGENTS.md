# AGENTS.md — `.github/`

CI, Dependabot, and pull-request templates. Parent: [../AGENTS.md](../AGENTS.md).

## Layout

| Path | Role |
| --- | --- |
| [`workflows/ci.yml`](workflows/ci.yml) | PR/main gates: Ruff, unittest, frontend lint + build |
| [`PULL_REQUEST_TEMPLATE.md`](PULL_REQUEST_TEMPLATE.md) | Required PR body sections for agents and humans |
| [`dependabot.yml`](dependabot.yml) | Weekly GitHub Actions, uv, and frontend npm updates |

## Conventions

- Inherit root [AGENTS.md](../AGENTS.md): minimal comments; update this file when CI jobs, ecosystems, or the PR template sections change.
- CI must not need provider API keys, LDView, or LPub3D.
- Keep the PR template sections stable; agents fill every heading (use `none` when empty).
- Do not commit `TASKS.md` from workflows or templates.

## Agent backlog

- #22 — Require CI status checks (and Bugbot) on main (filed 2026-09-26)
