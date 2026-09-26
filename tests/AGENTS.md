# AGENTS.md — `tests/`

Python regression tests for the deterministic geometry pipeline.

Parent / root: [../AGENTS.md](../AGENTS.md)

## Layout

| File | Coverage |
| --- | --- |
| `test_geometry.py` | Shape programs, fixed specialty pieces, rotated contacts/offsets, palette compatibility, aliases, packing / loose pieces, Pillow preview; optional official-library whitelist check |
| `test_providers.py` | Concept image toggle (`IMAGE_PROVIDER`) and design provider selection (`SCENE_PROVIDER`), key checks, OpenAI / Grok / Claude request shapes and error handling with the SDKs mocked, design / revise prompt assembly |
| `test_refine_api.py` | Refinement endpoint validation and idempotency, refine job generation (subprocesses mocked), `setup_problem`, infill prompts |
| `test_render.py` | LDView / LPub3D argv, timeouts and failure mapping with `subprocess` mocked; renderer and library discovery |
| `test_server.py` | Job orchestration: concept images start at queue time and `generate` reuses them (providers and design mocked) |
| `test_uploads.py` | `validate_upload`: accepted formats, payload shape, size, type mismatch, dimensions, animation, undecodable data |
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
  `catalog`, `render`, `web_assets`, `providers`, `uploads`, concept prefetch
  and the refinement endpoint in `server`, and `cli.refine_command`. Coverage
  of the rest of `cli` and `server` is thin—see Agent backlog.

## Agent backlog

- #54 — Tests for specialty-part CLI, provider and packaging paths (filed 2026-09-26)
- #49 — Add tests for web_assets and render (filed 2026-09-26) — closed by #57
- #48 — Add tests for providers and uploads (filed 2026-09-26) — closed by #58
- #47 — Add unit tests for CLI orchestration (filed 2026-09-26)
- #46 — Add unit tests for HTTP API / server.py (filed 2026-09-26)
- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
- #11 — Dynamically selected grid size (filed 2026-09-26) — see src/legolizer/AGENTS.md
