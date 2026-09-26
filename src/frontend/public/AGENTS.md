# AGENTS.md — `src/frontend/public/`

Vite static assets served at the site root (copied as-is; not processed by the
JS bundler).

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../../AGENTS.md](../../../AGENTS.md)

## Layout

| Path | Guide | Notes |
| --- | --- | --- |
| [`demo/`](demo/AGENTS.md) | yes | Bundled Little Bot / `robot-corrected` view-only set |

There are no other public trees today. Add an `AGENTS.md` if you introduce new
static trees (icons, fonts hosted locally, etc.).

## Conventions

- Prefer regenerating demo binaries via `../scripts/prepare_demo.py` rather
  than hand-editing packed MPD or license blobs.
- Large binaries in git affect clone time—file a perf/ops issue if the demo
  set grows substantially.

## Agent backlog

_(none yet)_
