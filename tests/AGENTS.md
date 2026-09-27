# AGENTS.md — `tests/`

Python unit and regression tests for the `legolizer` package.

Parent / root: [../AGENTS.md](../AGENTS.md)

## Layout

| File | Coverage |
| --- | --- |
| `test_generation_regressions.py` | Saved-design corpus and every design-guide example: exact coverage, visible colors, connectivity, support repair, and intentional build failures |
| [`fixtures/`](fixtures/AGENTS.md) | Saved shape programs from examples and real generations; no API keys or renderers required |
| `test_cli.py` | `build` (fixture JSON, saved program, review loop, concept inputs, unattached failures), `refine` errors and review, `_write_build` library checks, preview routing, specialty-piece report and review-loop persistence, `main` exit codes; bounded specialty supports and final pruning, invalid-program review budgets, saved failed inputs, exact imports, provider-free recovery; providers and pyldraw3 validation mocked |
| `test_geometry.py` | Shape programs, fixed specialty pieces, rotated contacts/offsets, palette compatibility, aliases, packing / loose pieces, symmetry-aware packing, plate-course repair, half-open decimal faces, Pillow preview, `examples/garden-gate.json` packs every specialty part; optional official-library whitelist check |
| `test_providers.py` | Concept image toggle (`IMAGE_PROVIDER`) and design provider selection (`SCENE_PROVIDER`), key checks, OpenAI / Grok / Claude request shapes and error handling with the SDKs mocked, design / revise / invalid-program prompt assembly, design prompt catalog coverage, design schema vs palette / specialty parts and the prompt example |
| `test_stylize.py` | Prompt stylizer: fast model + own system prompt and schema, palette filtering, category, size snapping, fallbacks to the original prompt; `design_guide` lookup and its place in the first design call |
| `test_sizing.py` | Size slider range and steps, `snap_size`, `estimate_size` (text and image), fast-model routing per provider |
| `test_refine_api.py` | Refinement endpoint validation and idempotency, refine job generation (subprocesses mocked), `setup_problem`, infill prompts |
| `test_render.py` | LDView / LPub3D argv, timeouts and failure mapping with `subprocess` mocked; renderer and library discovery |
| `test_server.py` | HTTP API over loopback (builds, jobs, assets allowlist, CORS / host checks, text and image submission, idempotency, 503 / 429), `generate` text / image / resume paths, concept prefetch at queue time, render / PDF failures, `initialize`, `setup_problem` renderer checks, directory lock, `main`; `aws` backend over moto (shared queue, presigned asset redirects, worker lease / on-demand start / idle exit, the Vercel entry point); worker, CLI and renderers mocked |
| `test_storage.py` | `LocalStore` and `AwsStore` over moto (table built from `src/infra/table-schema.json`): claims, reaping, publish, paging, presigned URLs, lease, `RunTask` arguments |
| `test_uploads.py` | `validate_upload`: accepted formats, payload shape, size, type mismatch, dimensions, animation, undecodable data |
| `test_web_assets.py` | `package_build` against a stub LDraw library: embedded subfiles, path normalization, copied assets, `build.json` metadata; optional official-library specialty-part embedding |
| `test_frontend_encoding.py` | Studio UI sources must not contain UTF-8-as-Windows-1252 mojibake (e.g. `â†’` instead of `→`) |

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
  `test_<module>.py` (geometry modules share `test_geometry.py`). The saved
  generation corpus lives in `fixtures/`, and `test_frontend_encoding.py`
  guards `src/frontend/src` against UTF-8 mojibake.

## Agent backlog

- #54 — Tests for specialty-part CLI, provider and packaging paths (filed 2026-09-26) — closed by #61
- #49 — Add tests for web_assets and render (filed 2026-09-26) — closed by #57
- #48 — Add tests for providers and uploads (filed 2026-09-26) — closed by #58
- #47 — Add unit tests for CLI orchestration (filed 2026-09-26) — closed by #59
- #46 — Add unit tests for HTTP API / server.py (filed 2026-09-26) — closed by #60
- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
- #11 — Dynamically selected grid size (filed 2026-09-26) — see src/legolizer/AGENTS.md
