# AGENTS.md — `tests/`

Python regression tests for the deterministic geometry pipeline.

Parent / root: [../AGENTS.md](../AGENTS.md)

## Layout

| File | Coverage |
| --- | --- |
| `test_geometry.py` | Shape programs (units, mirror, paint, carve), packing / loose pieces, hidden recolor, Pillow preview, MPD footprint export; optional official-library whitelist check |

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

- Inherit root [AGENTS.md](../AGENTS.md): minimal comments in tests too; update
  this file in the same change when coverage layout or run instructions change.
  Behavior-changing PRs must add tests (root rule 6); CI requires ≥75%
  **diff** coverage of changed `src/legolizer` lines.
- Framework: stdlib `unittest` + `coverage` + `diff-cover` (dev group). Config:
  `[tool.coverage.*]` in root `pyproject.toml`.
- Prefer extending `GeometryRegressionTests` with focused cases over new
  frameworks unless the human asks to migrate.
- Tests target `legolizer.shape`, `model`, `solver`, `preview`, `ldraw`,
  `catalog`. They do **not** currently cover `cli`, `server`, `providers`,
  `render`, `web_assets`, or `uploads`—see Agent backlog.

## Agent backlog

- #49 — Add tests for web_assets and render (filed 2026-09-26)
- #48 — Add tests for providers and uploads (filed 2026-09-26)
- #47 — Add unit tests for CLI orchestration (filed 2026-09-26)
- #46 — Add unit tests for HTTP API / server.py (filed 2026-09-26)
- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
- #11 — Dynamically selected grid size (filed 2026-09-26) — see src/legolizer/AGENTS.md
- #2 — Support more LEGO bricks (filed 2026-09-26) — see src/legolizer/AGENTS.md
