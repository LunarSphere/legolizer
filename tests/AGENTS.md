# AGENTS.md — `tests/`

Python regression tests for the deterministic geometry pipeline.

Parent / root: [../AGENTS.md](../AGENTS.md)

## Layout

| File | Coverage |
| --- | --- |
| `test_geometry.py` | Shape programs, fixed specialty pieces, rotated contacts/offsets, palette compatibility, aliases, packing / loose pieces, Pillow preview; optional official-library whitelist check |

Run from repo root:

```sh
uv run python -m unittest discover -s tests -v
```

Set `LDRAW_LIBRARY_PATH` to a directory containing `parts.lst` to enable
`test_whitelist_dimensions_match_official_geometry`. Other tests do not need
API keys or the library.

## Conventions

- Inherit root [AGENTS.md](../AGENTS.md): minimal comments in tests too; update
  this file in the same change when coverage layout or run instructions change.
- Framework: stdlib `unittest` (no pytest config in `pyproject.toml`).
- Prefer extending `GeometryRegressionTests` with focused cases over new
  frameworks unless the human asks to migrate.
- Tests target `legolizer.shape`, `model`, `solver`, `preview`, `ldraw`,
  `catalog`. They do **not** currently cover `cli`, `server`, `providers`,
  `render`, `web_assets`, or `uploads`.
- If you notice missing coverage while working on those modules, file a GitHub
  issue and note it under **Agent backlog** here (and in
  [`../src/legolizer/AGENTS.md`](../src/legolizer/AGENTS.md))—do not expand
  scope mid-task.

## Agent backlog

- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
- #11 — Dynamically selected grid size (filed 2026-09-26) — see src/legolizer/AGENTS.md
- #2 — Support more LEGO bricks (filed 2026-09-26) — see src/legolizer/AGENTS.md
