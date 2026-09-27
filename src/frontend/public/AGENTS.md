# AGENTS.md — `src/frontend/public/`

Vite static assets served at the site root (copied as-is; not processed by the
JS bundler).

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../../AGENTS.md](../../../AGENTS.md)

## Layout

| Path | Guide | Notes |
| --- | --- | --- |
| [`demo/`](demo/AGENTS.md) | yes | Bundled Little Bot / `robot-corrected` view-only set |
| `privacy.html` | — | Standalone privacy policy at `/privacy.html`. It exists only so Google sign-in can be enabled: Google's OAuth consent screen requires a privacy policy URL. Not linked from the studio. Update it when data handling or providers change |

There are no other public trees today. Add an `AGENTS.md` if you introduce new
static trees (icons, fonts hosted locally, etc.).

## Conventions

- Inherit root [AGENTS.md](../../../AGENTS.md): minimal comments; update this
  file in the same change when static trees or regeneration rules change.
- Prefer regenerating demo binaries via `../scripts/prepare_demo.py` rather
  than hand-editing packed MPD or license blobs.
- Large binaries in git affect clone time—file a perf/ops issue if the demo
  set grows substantially.

## Agent backlog

- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
