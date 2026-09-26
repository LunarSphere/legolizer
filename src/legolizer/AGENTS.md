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
| `providers.py` | Concept image (OpenAI or Grok Imagine via `IMAGE_PROVIDER`) + OpenAI / Anthropic / Grok design + revise (`SCENE_PROVIDER`), and infill `design_infill` / `revise_infill` |
| `cli.py` | `build` and `refine` (parallel infill candidates) orchestration and disk outputs |
| `server.py` | Local HTTP API, job queue (1 worker; text-job concept images start at queue time in a 3-thread pool; render and PDF export run side by side), asset serving |
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
- Box faces and cylinder ends use tolerant half-open bounds. Preserve their
  inclusive lower/exclusive upper faces so decimal roundoff cannot drop a shared
  voxel course; the saved lighthouse regression exercises this.
- Explicit `pieces` use integer stud x/y and plate-level z, with four upright
  rotations. `voxel_document` must receive `Voxelized.pieces` to preserve them.
  Their envelopes replace primitive cells; exported geometry stays official.
- Only `RECTANGULAR_PARTS` enter greedy/repair tiling. Explicit pieces remain
  fixed, with rotated stud/socket masks for connectivity and native offsets
  for export. Do not treat tile tops or arch openings as attachment points.
- Specialty previews use the official renderer through `cli._render_build_preview`;
  each subprocess has a 120-second timeout. Ordinary programs retain Pillow
  voxel views. Details/examples: root README.
- Generated-program refinement may add short columns under disconnected explicit
  sockets (at most 8 columns, 6 plate levels each), accepted only after a better
  connectivity result. Imported CLI geometry stays exact. Assembly recovery uses
  saved programs when available and avoids provider calls.
- Refinement saves `program.vN.json` before validation. Invalid programs receive
  textual repair feedback within the existing review budget; exhaustion retains
  the best valid round or raises if none exists.
- Final generated-only pruning can remove at most 8 loose pieces, 5% of pieces,
  and 2% of envelope cells. It preserves retained placements, rechecks connectivity,
  and saves the source and removal manifest. No repack or provider calls. Shape
  voxelization exposes `ground_offset` for edits in original program coordinates.
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
(`tests/test_geometry.py`); `cli`, `providers`, `uploads`, `render`, and
`web_assets` each have their own `tests/test_<module>.py`. The server is
covered only for refinements—see backlog (#46). Behavior-changing PRs must add tests (root AGENTS rule 6); CI requires ≥75% coverage of
**changed** `src/legolizer` lines (diff-cover), not whole-package %.

## Performance-sensitive areas

File a GitHub issue (and note below) if you see clear wins; do not drive-by
optimize unless the task asks for it.

- `solver.pack` — multi-restart greedy scan + `_repair` backtracking; symmetric
  voxel models may use one additional bounded attempt to prefer mirrored layouts
- First-attempt repair may retile at most 6,000 cells near loose parts with
  plates. Offset alternate courses only for loose plates wider than the existing
  48-cell course-repair limit; ordinary dome repair keeps its faster scan. Other
  placements and all explicit parts remain fixed.
- `shape._part_cells` — per-primitive volume loops
- `web_assets.package_build` — recursive official-part embedding (I/O)
- `providers` — large token completions; network-bound
- `server` — `ThreadPoolExecutor(max_workers=1)`; render/PDF subprocess timeouts

## When changing the HTTP API

Update `server.py` **and** keep [`../frontend/api/openapi.json`](../frontend/api/openapi.json)
in sync. Frontend client: `../frontend/src/api.js`.

## Agent backlog

- #54 — Tests for specialty-part CLI, provider and packaging paths (filed 2026-09-26) — see tests/AGENTS.md
- #49 — Add tests for web_assets and render (filed 2026-09-26) — closed by #57
- #48 — Add tests for providers and uploads (filed 2026-09-26) — closed by #58
- #47 — Add unit tests for CLI orchestration (filed 2026-09-26) — closed by #59
- #46 — Add unit tests for HTTP API / server.py (filed 2026-09-26) — see tests/AGENTS.md
- #44 — Generate concept images for queued text builds in parallel (filed 2026-09-26)
- #64 — Grok as the design provider (filed 2026-09-26)
- #42 — Grok Imagine concept image pipeline (filed 2026-09-26)
- #41 — Env toggle for the concept image provider (filed 2026-09-26)
- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
- #11 — Dynamically selected grid size (filed 2026-09-26)
- #9 — AWS backend (filed 2026-09-26)
- #6 — User accounts with saved models (filed 2026-09-26)
- #5 — Reprompt / generative infill on a region (filed 2026-09-26) — closed by #24
