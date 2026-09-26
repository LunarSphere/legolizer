# AGENTS.md — `tests/`

Python regression tests for the deterministic geometry pipeline.

Parent / root: [../AGENTS.md](../AGENTS.md)

## Layout

| File | Coverage |
| --- | --- |
| `test_geometry.py` | Shape programs, fixed specialty pieces, rotated contacts/offsets, palette compatibility, aliases, packing / loose pieces, Pillow preview; optional official-library whitelist check |
| `test_providers.py` | Concept image provider toggle (`IMAGE_PROVIDER`), key checks, OpenAI / Grok request shapes with the SDK mocked |
| `test_refine_api.py` | Refinement endpoint, refine job `generate` path (CLI and renderers mocked), `setup_problem`, infill prompts |
| `test_render.py` | LDView / LPub3D argv, timeouts and failure mapping with `subprocess` mocked; renderer and library discovery |
| `test_web_assets.py` | `package_build` against a stub LDraw library: embedded subfiles, path normalization, copied assets, `build.json` metadata |

Run from repo root (same as CI):

```sh
uv run coverage run -m unittest discover -s tests -v
uv run coverage report
uv run coverage xml
uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=75 --include=src/legolizer/*
```

Plain discover without coverage still works:
`uv run python -m unittest discover -s tests -v`.

Set `LDRAW_LIBRARY_PATH` to a directory containing `parts.lst` to enable
`test_whitelist_dimensions_match_official_geometry`. Other tests do not need
API keys or the library.

## Conventions

- **Tests never run generation.** No real provider calls (OpenAI, Anthropic,
  Grok), no LDView / LPub3D subprocesses, and no end-to-end `server.generate`,
  `build_command` or `refine_command` run that reaches a network or renderer.
  Mock `legolizer.providers` functions or the SDK clients, `subprocess`, and
  `render_model`; use offline seams (`--fixture-json`, `--program`, fake
  design responses). Generation is slow, costs money and needs keys CI lacks.
- Inherit root [AGENTS.md](../AGENTS.md): minimal comments in tests too; update
  this file in the same change when coverage layout or run instructions change.
  Behavior-changing PRs must add tests (root rule 6); CI requires ≥75%
  **diff** coverage of changed `src/legolizer` lines.
- Framework: stdlib `unittest` + `coverage` + `diff-cover` (dev group). Config:
  `[tool.coverage.*]` in root `pyproject.toml`.
- Prefer extending `GeometryRegressionTests` with focused cases over new
  frameworks unless the human asks to migrate.
- Tests target `legolizer.shape`, `model`, `solver`, `preview`, `ldraw`,
  `catalog`, `render`, `web_assets`, the concept image part of `providers`,
  and the refinement parts of `server` and `cli`. Coverage of the rest of
  `cli`, `server`, the design half of `providers`, and `uploads` is thin—see
  Agent backlog.

## Agent backlog

- #54 — Tests for specialty-part CLI, provider and packaging paths (filed 2026-09-26)
- #49 — Add tests for web_assets and render (filed 2026-09-26)
- #48 — Add tests for providers and uploads (filed 2026-09-26)
- #47 — Add unit tests for CLI orchestration (filed 2026-09-26)
- #46 — Add unit tests for HTTP API / server.py (filed 2026-09-26)
- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
- #11 — Dynamically selected grid size (filed 2026-09-26) — see src/legolizer/AGENTS.md
