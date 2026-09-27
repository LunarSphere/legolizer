# Tests

## Summary
`unittest` suite under `tests/` covering geometry/export, CLI, server/auth,
storage, providers, uploads, refine, and related regressions. CI runs coverage
plus diff-cover ≥75% on changed `src/legolizer` lines.

## Key modules / paths
- `tests/test_geometry.py` — packing / geometry
- `tests/test_cli.py` — CLI orchestration
- `tests/test_server.py` — HTTP API / Vercel entry
- `tests/test_storage.py` — LocalStore / AwsStore
- `tests/test_auth.py` — Google sessions
- `tests/test_providers.py`, `test_stylize.py`, `test_sizing.py`, `test_reference.py`
- `tests/test_uploads.py`, `test_web_assets.py`, `test_render.py`, `test_refine_api.py`
- `tests/test_generation_regressions.py` — fixture pipelines

## Invariants
- Behavior-changing PRs extend tests (root AGENTS rule 6)
- CI: Ruff + unittest; ≥75% diff-cover on changed `src/legolizer` lines
- Prefer extending existing modules over inventing a second harness mid-feature

## Last updated
2026-09-27
