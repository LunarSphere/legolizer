# Providers and CLI

## Summary
LLM and image providers drive concept art, design, revise, stylize, sizing, and
infill. The CLI orchestrates offline-capable builds/refines and optional
LDView/LPub3D renders. Reference photos and upload validation feed the pipeline.

## Key modules / paths
- `src/legolizer/providers.py` — concept/design/revise/stylize/infill adapters
- `src/legolizer/cli.py` — `build` / `refine` / render orchestration
- `src/legolizer/reference.py` — optional Wikipedia lead images
- `src/legolizer/uploads.py` — bounded browser image validation
- `src/legolizer/render.py` — LDView / LPub3D subprocesses; the server's web
  `render.png` uses `--transparent` (LDView alpha), review previews stay opaque
- `src/legolizer/guides/` — category JSON guides for designers

## Invariants
- Lazy-import providers from CLI so fixture/program paths stay offline
- `IMAGE_PROVIDER` / `SCENE_PROVIDER` / `FAST_PROVIDER` routing per env
- Upload bodies stay under Vercel request limits

## Last updated
2026-09-27 (#116)
