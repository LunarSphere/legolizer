# AGENTS.md — `tests/`

Python unit and regression tests for the `legolizer` package.

Parent / root: [../AGENTS.md](../AGENTS.md)

## Layout

| File | Coverage |
| --- | --- |
| `test_cli.py` | `build` (fixture JSON, saved program, review loop, concept inputs, unattached failures), `refine` errors and review, `_write_build` library checks, preview routing, specialty-piece report and review-loop persistence, `main` exit codes; providers and pyldraw3 validation mocked |
| `test_geometry.py` | Shape programs, fixed specialty pieces, rotated contacts/offsets, palette compatibility, aliases, packing / loose pieces, Pillow preview, `examples/garden-gate.json` packs every specialty part; optional official-library whitelist check |
| `test_providers.py` | Concept image toggle (`IMAGE_PROVIDER`) and design provider selection (`SCENE_PROVIDER`), key checks, OpenAI / Grok / Claude request shapes and error handling with the SDKs mocked, design / revise prompt assembly, design schema vs palette / specialty parts and the prompt example |
| `test_refine_api.py` | Refinement endpoint, refine job `generate` path (CLI and renderers mocked), `setup_problem`, infill prompts |
| `test_render.py` | LDView / LPub3D argv, timeouts and failure mapping with `subprocess` mocked; renderer and library discovery |
| `test_server.py` | HTTP API over loopback (builds, jobs, assets allowlist, CORS / host checks, text and image submission, idempotency, 503 / 429), `generate` text / image / resume paths and render / PDF failures, `initialize`, `setup_problem` renderer checks, directory lock, `main`; worker, CLI and renderers mocked |
| `test_uploads.py` | `validate_upload`: accepted formats, payload shape, size, type mismatch, dimensions, animation, undecodable data |
| `test_web_assets.py` | `package_build` against a stub LDraw library: embedded subfiles, path normalization, copied assets, `build.json` metadata; optional official-library specialty-part embedding |

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
`test_whitelist_dimensions_match_official_geometry` and
`test_official_library_embeds_specialty_parts`. Other tests do not need API
keys or the library.

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
- Every module in `legolizer` has tests. Put new cases in the matching
  `test_<module>.py` (geometry modules share `test_geometry.py`).

## Agent backlog

- #54 — Tests for specialty-part CLI, provider and packaging paths (filed 2026-09-26)
- #49 — Add tests for web_assets and render (filed 2026-09-26) — closed by #57
- #48 — Add tests for providers and uploads (filed 2026-09-26) — closed by #58
- #47 — Add unit tests for CLI orchestration (filed 2026-09-26) — closed by #59
- #46 — Add unit tests for HTTP API / server.py (filed 2026-09-26) — closed by #60
- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
- #11 — Dynamically selected grid size (filed 2026-09-26) — see src/legolizer/AGENTS.md
