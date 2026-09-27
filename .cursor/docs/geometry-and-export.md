# Geometry and export

## Summary
Turns shape programs into packed official LDraw geometry: whitelist parts,
voxelize, greedy pack with connectivity, write stepped MPD/parts lists, and
package browser-ready models. Preview helpers support LLM review loops.

## Key modules / paths
- `src/legolizer/catalog.py` — official parts, colors, contact masks
- `src/legolizer/shape.py` — shape programs, voxelize, edit zones
- `src/legolizer/model.py` — voxel/placement types
- `src/legolizer/solver.py` — pack / solve / repack_region
- `src/legolizer/ldraw.py` — MPD + parts.json read/write
- `src/legolizer/preview.py` — Pillow orthographic/iso previews
- `src/legolizer/web_assets.py` — embed official subfiles for WebGL

## Invariants
- Only official whitelist parts; no invented geometry
- Stud units / plate-level z; hard grid `MAX_STUDS` 32; target size 16–32 step 4
- `read_mpd` stays inverse of `write_mpd`

## Last updated
2026-09-27
