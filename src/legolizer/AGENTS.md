# AGENTS.md — `src/legolizer/`

Flat Python package (no nested packages). Entry points:

- CLI: `legolizer` → `cli:main` (`uv run legolizer build|render …`)
- Server: `python -m legolizer.server` (loopback `127.0.0.1:8000`)

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../AGENTS.md](../../AGENTS.md)

## Module map

| Module | Responsibility |
| --- | --- |
| `catalog.py` | Official part whitelist, 15 designer colors, contact masks, native offsets |
| `shape.py` | Shape-program schema + `voxelize_program` / `voxel_document` |
| `model.py` | `Voxel` / `VoxelModel` / `Placement`, validated explicit pieces and reserved envelopes |
| `solver.py` | Greedy packer, repair, stud connectivity (`pack` / `solve`) |
| `preview.py` | Pillow orthographic + iso previews for the LLM reviewer |
| `ldraw.py` | Stepped MPD + `parts.json` (BrickLink links) |
| `render.py` | LDView / LPub3D subprocess PNG render |
| `providers.py` | OpenAI / Anthropic concept + design + revise |
| `cli.py` | Build/refine loop orchestration and disk outputs |
| `server.py` | Local HTTP API, job queue (1 worker), asset serving |
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

## Tests

Geometry/export regressions live in [`../../tests/`](../../tests/AGENTS.md)
(`tests/test_geometry.py`). CLI, server, providers, uploads, and web_assets are
largely untested—file issues rather than silent scope expansion if you notice
gaps while working elsewhere.

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

- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
- #11 — Dynamically selected grid size (filed 2026-09-26)
- #9 — AWS backend (filed 2026-09-26)
- #6 — User accounts with saved models (filed 2026-09-26)
- #5 — Reprompt / generative infill on a region (filed 2026-09-26)
- #2 — Support more LEGO bricks (filed 2026-09-26)
