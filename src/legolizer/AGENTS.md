# AGENTS.md — `src/legolizer/`

Flat Python package (no nested packages). Entry points:

- CLI: `legolizer` → `cli:main` (`uv run legolizer build|render …`)
- Server: `python -m legolizer.server` (loopback `127.0.0.1:8000`)

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../AGENTS.md](../../AGENTS.md)

## Module map

| Module | Responsibility |
| --- | --- |
| `catalog.py` | Official part whitelist, 15 designer colors, contact masks, native offsets |
| `shape.py` | Shape-program schema + `voxelize_program` / `voxel_document`; zone `infill` / `parse_selection` / `edit_zone` |
| `model.py` | `Voxel` / `VoxelModel` / `Placement`, validated explicit pieces and reserved envelopes |
| `solver.py` | Greedy packer, repair, stud connectivity (`pack` / `solve`); `repack_region` keeps outside and unchanged pieces |
| `preview.py` | Pillow orthographic + iso previews for the LLM reviewer (optional edit-zone outlines) |
| `ldraw.py` | Stepped MPD + `parts.json` (BrickLink links); `read_mpd` reads placements back |
| `render.py` | LDView / LPub3D subprocess PNG render |
| `providers.py` | Concept image (OpenAI or Grok Imagine via `IMAGE_PROVIDER`) + OpenAI / Anthropic design + revise, and infill `design_infill` / `revise_infill` |
| `cli.py` | `build` and `refine` (parallel infill candidates) orchestration and disk outputs |
| `server.py` | Local HTTP API, job queue (1 worker; render and PDF export run side by side), asset serving |
| `web_assets.py` | Embed official subfiles into `packed.mpd` + `build.json` |
| `uploads.py` | Base64 image validation for Image → LEGO |

Pipeline: concept (optional) → shape program → voxels → pack → preview/review
loop → MPD/parts → render/PDF → `package_build` (server path).

## Conventions

- Inherit root [AGENTS.md](../../AGENTS.md): minimal comments (non-narrative;
  only when code is unclear); update this file in the same change when the
  module map, conventions, or performance notes shift.
- Prefer `from __future__ import annotations` and frozen dataclasses for
  geometry types.
- Lazy-import providers from `cli.py` so `--fixture-json` / `--program` stay
  offline.
- User/input failures → `ValueError`; missing tools/keys/loose pieces →
  `RuntimeError`. CLI maps those to exit 1.
- Env: see root `.env.example`. Server data root: `LEGOLIZER_DATA_DIR` or
  `builds/studio/`.
- **Do not** invent brick geometry. Extend `PARTS` in `catalog.py` only with
  real LDraw part codes and correct stud footprints.
- Shape programs use stud units on all axes (`PLATE = 0.4`); voxel `z` is
  plate-level.
- Explicit `pieces` use integer stud x/y and plate-level z, with four upright
  rotations. `voxel_document` must receive `Voxelized.pieces` to preserve them.
  Their envelopes replace primitive cells; exported geometry stays official.
- Only `RECTANGULAR_PARTS` enter greedy/repair tiling. Explicit pieces remain
  fixed, with rotated stud/socket masks for connectivity and native offsets
  for export. Do not treat tile tops or arch openings as attachment points.
- Specialty previews use the official renderer through `cli._render_build_preview`;
  each subprocess has a 120-second timeout. Ordinary programs retain Pillow
  voxel views. Details/examples: root README.
- Refinement (generative infill) edits only the selected pieces plus one brick
  around each (`edit_zone`), or the whole model with no selection. It never
  lowers the model to the ground and never edits the parent build directory;
  results go to a new build. Parts may carry an optional `clip` (one box or a
  list of boxes; not in `PART_SCHEMA`, so designers cannot emit it).
- `refine_command` requests candidate patches in parallel threads and reviews
  only when the best one has problems; providers build a fresh client per call.
- Infill keeps the parent's explicit pieces fixed and adds patch pieces only
  when their whole envelope is inside the zone. `read_mpd` must stay the exact
  inverse of `write_mpd` (rotation matrices and native offsets).

## Tests

Geometry/export regressions live in [`../../tests/`](../../tests/AGENTS.md)
(`tests/test_geometry.py`); concept-image provider coverage is in
`tests/test_providers.py`. `render` and `web_assets` have their own suites.
CLI, server, design-half providers, and uploads remain largely untested—see backlog (#46–#49). Behavior-changing
PRs must add tests (root AGENTS rule 6); CI requires ≥75% coverage of
**changed** `src/legolizer` lines (diff-cover), not whole-package %.

## Performance-sensitive areas

File a GitHub issue (and note below) if you see clear wins; do not drive-by
optimize unless the task asks for it.

- `solver.pack` — multi-restart greedy scan + `_repair` backtracking
- `shape._part_cells` — per-primitive volume loops
- `web_assets.package_build` — recursive official-part embedding (I/O)
- `providers` — large token completions; network-bound
- `server` — `ThreadPoolExecutor(max_workers=1)`; render/PDF subprocess timeouts

## When changing the HTTP API

Update `server.py` **and** keep [`../frontend/api/openapi.json`](../frontend/api/openapi.json)
in sync. Frontend client: `../frontend/src/api.js`.

## Agent backlog

- #54 — Tests for specialty-part CLI, provider and packaging paths (filed 2026-09-26) — see tests/AGENTS.md
- #49 — Add tests for web_assets and render (filed 2026-09-26) — see tests/AGENTS.md
- #48 — Add tests for providers and uploads (filed 2026-09-26) — see tests/AGENTS.md
- #47 — Add unit tests for CLI orchestration (filed 2026-09-26) — see tests/AGENTS.md
- #46 — Add unit tests for HTTP API / server.py (filed 2026-09-26) — see tests/AGENTS.md
- #42 — Grok Imagine concept image pipeline (filed 2026-09-26)
- #41 — Env toggle for the concept image provider (filed 2026-09-26)
- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
- #11 — Dynamically selected grid size (filed 2026-09-26)
- #9 — AWS backend (filed 2026-09-26)
- #6 — User accounts with saved models (filed 2026-09-26)
- #5 — Reprompt / generative infill on a region (filed 2026-09-26) — closed by #24
