# AGENTS.md — `.github/`

CI, Dependabot, and pull-request templates. Parent: [../AGENTS.md](../AGENTS.md).

## Layout

| Path | Role |
| --- | --- |
| [`workflows/ci.yml`](workflows/ci.yml) | PR/main gates: Ruff, unittest + coverage, PR diff-cover ≥75%, frontend lint + build |
| [`workflows/infra.yml`](workflows/infra.yml) | Path-filtered (infra, server, `api/`, deps): CDK type-check + synth without credentials; Docker build + `validate-local.sh` smoke test |
| [`workflows/deploy.yml`](workflows/deploy.yml) | CD on pushes to `main` (same paths as `infra.yml`) and manual dispatch: `validate-local.sh`, OIDC into `LegolizerDeploy`, `deploy.sh` without writing secrets; optional Vercel deploy |
| [`PULL_REQUEST_TEMPLATE.md`](PULL_REQUEST_TEMPLATE.md) | Required PR body sections for agents and humans |
| [`dependabot.yml`](dependabot.yml) | Weekly GitHub Actions, uv, and frontend npm updates |

## Conventions

- Inherit root [AGENTS.md](../AGENTS.md): minimal comments; update this file when CI jobs, ecosystems, or the PR template sections change.
- CI must not need provider API keys or AWS credentials. Only `infra.yml` runs LDView /
  LPub3D, inside the Docker image. Keep `ci.yml` untouched by deployment work.
- Only `deploy.yml` gets AWS access, through OIDC in the `aws-production` environment
  (not Vercel's `Production`);
  never store AWS keys or provider keys in GitHub secrets.
- Python tests run under `coverage`. On pull_request, `diff-cover` requires ≥75%
  coverage of changed lines under `src/legolizer/` (root AGENTS rule 6).
- Keep the PR template sections stable; agents fill every heading (use `none` when empty).
- Do not commit `TASKS.md` from workflows or templates.

## Agent backlog

- #50 — Add frontend test suite and CI job (filed 2026-09-26) — see src/frontend/AGENTS.md
- #22 — Require CI status checks on main (filed 2026-09-26)
