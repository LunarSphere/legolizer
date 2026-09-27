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
- Stud units / plate-level z; grid caps in catalog/solver conventions
- `read_mpd` stays inverse of `write_mpd`

## Last updated
2026-09-27 (#116)
