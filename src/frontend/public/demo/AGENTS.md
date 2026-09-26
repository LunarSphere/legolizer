# AGENTS.md — `src/frontend/public/demo/`

Static **demo build** for `VITE_DEMO=true` (and default showcase id
`robot-corrected` / Little Bot). Served as `/demo/…`.

Parent: [../AGENTS.md](../AGENTS.md) · Frontend: [../../AGENTS.md](../../AGENTS.md) ·
Root: [../../../../AGENTS.md](../../../../AGENTS.md)

## Files

| File | Purpose |
| --- | --- |
| `build.json` | Metadata + asset URL map for the demo set |
| `parts.json` | Quantities, colors, BrickLink links |
| `packed.mpd` | Self-contained MPD (embedded official geometry) for WebGL |
| `model.mpd` | Original MPD for download |
| `LDConfig.ldr` | Materials for `LDrawLoader.preloadMaterials` |
| `render.png` | Preview / fallback image |
| `build-guide.pdf` | LPub3D instructions |
| `readme.txt`, `careadme.txt`, `calicense*.txt` | Upstream LDraw/library licenses |

## Conventions

- Regenerate with [`../../scripts/prepare_demo.py`](../../scripts/AGENTS.md)
  from a completed build directory that already has `model.mpd`, `parts.json`,
  `build-guide.pdf`, and `render.png`.
- Keep license headers and license text files intact when refreshing.
- Demo title/id defaults are set in the prepare script—update script + JSON
  together if rebranding the showcase.
- Do not strip embedding from `packed.mpd`; the viewer must not fetch a remote
  parts library.

## Agent backlog

_(none yet)_
