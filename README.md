# Legolizer

Turn a short object description into a voxelized LEGO-style model, a stepped LDraw MPD, a parts list, and a render. The proof of concept uses only a small whitelist of official rectangular LDraw bricks and plates. It does not create or approximate part geometry.

## Local React frontend

Start the local API from the repository root with `uv run python -m legolizer.server`
(it reads the same `.env` as the CLI, and needs LDView and LPub3D installed).
Then start the frontend below.

The viewer in [`src/frontend`](src/frontend/README.md) includes the corrected
robot demo, orbit/pan/zoom controls, model position sliders, visibility settings,
PDF instructions, and a color-aware parts purchase list. Generate from text or upload an image (PNG/JPEG/WebP, up to 4 MB), then switch
between saved sets; completed builds persist under `builds/studio/`. Use
**Select** in the viewer to pick bricks and reprompt just those bricks, or
reprompt the whole model with nothing selected.

```sh
cd src/frontend
npm ci
npm run dev -- --port 5173 --strictPort
```

Requires Node.js 22.12+; open http://127.0.0.1:5173. Generation uses your server API keys. Set `VITE_DEMO=true` for a view-only demo.
The REST API contract is [`src/frontend/api/openapi.json`](src/frontend/api/openapi.json).
Vite proxies the local API automatically; see the frontend README for configuration.

## Requirements

See [instructions.md](instructions.md) for software installation, API credentials,
and the complete macOS and Windows setup for rendering and PDF build guides.

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- An OpenAI API key for live generation (an Anthropic key is optional)
- LDView or LPub3D for rendering (optional)
- An LDraw library, downloaded and configured by the setup commands below

```sh
uv sync
uv run ldraw download --yes
uv run ldraw generate --yes
```

Set the credentials and optional model/library configuration. On Windows
PowerShell, use `$env:NAME = "value"`; in Command Prompt, use `set NAME=value`.
For a persistent setup on any platform, copy `.env.example` to `.env` and put
your values there. The `legolizer` command loads `.env` from the current
directory (or a parent), while already-set environment variables take precedence.

PowerShell:

```powershell
$env:OPENAI_API_KEY = "..."
$env:ANTHROPIC_API_KEY = "..."
$env:OPENAI_IMAGE_MODEL = "gpt-image-1"
$env:CLAUDE_MODEL = "claude-sonnet-4-6"
# Optional: point at installed renderer executables
$env:LPUB3D_BIN = "C:\Program Files\LPub3D\LPub3D.exe"
$env:LDVIEW_BIN = "C:\Program Files\LDView\LDView64.exe"
# Optional: override pyldraw3's configured LDraw library for validation and rendering
$env:LDRAW_LIBRARY_PATH = "C:\Path\To\ldraw"
```

POSIX shell:

```sh
export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."
export OPENAI_IMAGE_MODEL="gpt-image-1"
export CLAUDE_MODEL="claude-sonnet-4-6"
export LPUB3D_BIN="/Applications/LPub3D.app/Contents/MacOS/LPub3D"
export LDVIEW_BIN="/Applications/LDView.app/Contents/MacOS/LDView"
export LDRAW_LIBRARY_PATH="/path/to/ldraw"
```

To use an existing LDraw library, set its path in pyldraw3's `config.yml`; inspect the active settings with `uv run ldraw config`.

API keys are needed only for live generation; calls may incur provider charges.

## How it works

1. **Concept image (optional).** An image model draws one 3/4 picture of the
   object as a brick model. It guides colors, proportions and which features
   matter. It is never measured, so its inaccuracies cannot become geometry.
2. **Shape program.** A vision model (Claude if `ANTHROPIC_API_KEY` is set,
   otherwise OpenAI's `OPENAI_SCENE_MODEL`, default `gpt-5`; override with
   `SCENE_PROVIDER`) writes the object as an ordered list of 3D primitives:
   boxes, ellipsoids and cylinders with taper, left/right mirroring, and
   solid/paint/carve modes, in uniform stud units. Responses are forced to a
   JSON schema. This program is the single 3D source of truth.
3. **Voxelize.** Python converts the program to 1 stud × 1 stud × 1 plate
   cells, reporting parts that were clipped, covered, or had no effect.
4. **Pack.** The solver covers the cells with official bricks and plates,
   staggers seams across restarts, repairs pieces that only touch sideways,
   and lets hidden interior cells take any color. It reports every piece not
   attached to the main build through studs, named by the program part it came
   from.
5. **Review.** Exact front, right, top and 3/4 renders of the cells, plus that
   build report, go back to the vision model. It critiques them against the
   description and concept and returns a corrected program. This repeats for
   `--iterations` rounds (default 2), and the best round is kept: fewest
   unattached pieces, then the latest.

Every image the reviewer sees is rendered from the same cells that are built,
so views cannot contradict each other and the model sees its own mistakes.

## Build a model

```sh
uv run legolizer build "a small red and blue delivery truck" --out builds/truck
```

The output directory contains:

| File | Contents |
| --- | --- |
| `concept.png` | The concept image |
| `program.json`, `program.vN.json` | The chosen shape program, and every round's |
| `preview.png`, `preview.vN.png` | Renders of the chosen round, and every round's |
| `design.log` | The reviewer's assessments and each round's build report |
| `model.json` | The voxel document |
| `model.mpd`, `parts.json` | The stepped LDraw model and the parts list |

Options:

- `--no-concept` designs from the text alone, which is cheaper and faster.
- `--concept image.png` uses your own reference picture instead of generating
  one. `--views` is accepted as an older alias.
- `--program builds/truck/program.json` rebuilds from a saved (or hand-edited)
  program without API calls. Add `--iterations 1` to have it reviewed again.
- `--iterations N` sets the number of review rounds.
- `--fixture-json model.json` packs a voxel document and skips every API.

A build with unattached pieces still writes its files for inspection, then
exits with an error that lists the pieces.

## Refine selected bricks (generative infill)

Regenerate selected bricks of a finished build from a new prompt. The original
directory is left unchanged:

```sh
uv run legolizer refine builds/truck "add a yellow roof light" \
  --select 4,3,12,5,4,14 --out builds/truck-light
```

Each `--select x0,y0,z0,x1,y1,z1` is one selected brick's inclusive cells: x and
y in studs, z in plates (three per brick). Repeat it for more bricks. Only the
selected bricks plus one brick around each (one stud sideways, three plates up
and down) may change. The designer returns a patch program whose parts are
clipped to that zone, so cells outside it never change and pieces entirely
outside it keep their placement. Pieces inside the zone that the edit leaves
as they were are also kept when the model stays connected. Without `--select`
the patch may change the whole model.

Several candidate patches (`--candidates`, default `LEGOLIZER_INFILL_CANDIDATES`
or 3) are requested in parallel. Each one is packed and scored as soon as it
arrives. The best candidate has the fewest unattached pieces, then changed
something, then has the fewest voxelizer notes, then the fewest rebuilt pieces.
A render-and-review round runs only if the best candidate still has a problem.
`refine.json` records the request, the selection, the zone, the clipped patch,
and the rebuilt pieces. When the original has a `program.json`, the refined
build's program is the original plus the clipped patch parts (each with a
`clip` list of zone boxes), so it re-voxelizes to the same model. In the
studio, choose **Select**, click bricks (or none for a whole-model edit), and
describe the change; the result is saved as a new set.

### Shape programs

All values are in stud units (1 unit = 8 mm) on every axis, so a brick is
1.2 units tall and a plate 0.4. X runs left to right, Y = 0 is the front,
and Z = 0 is the ground; the build volume is 20 × 20 × 24 units.

```json
{
  "name": "red mushroom",
  "size": [8, 8, 6.4],
  "parts": [
    {"name": "cap", "shape": "ellipsoid", "mode": "solid", "center": [4, 4, 3.2], "size": [8, 8, 6.4], "axis": "z", "taper": 1, "color": 4, "mirror": false},
    {"name": "cap underside", "shape": "box", "mode": "carve", "center": [4, 4, 1.6], "size": [8, 8, 3.2], "axis": "z", "taper": 1, "color": 4, "mirror": false},
    {"name": "stem", "shape": "cylinder", "mode": "solid", "center": [4, 4, 1.8], "size": [3, 3, 3.6], "axis": "z", "taper": 1, "color": 15, "mirror": false},
    {"name": "left spot", "shape": "ellipsoid", "mode": "paint", "center": [2, 3, 5], "size": [2, 2, 1.2], "axis": "z", "taper": 1, "color": 15, "mirror": true}
  ]
}
```

Parts apply in order: `solid` fills cells, `paint` recolors cells that are
already filled, and `carve` removes cells. `taper` shrinks a box or cylinder
toward the + end of its `axis`. `mirror` adds a copy reflected across
X = `size[0]` / 2.

### Voxel fixtures

`--fixture-json` takes `width`, `depth`, `height` (width/depth in studs;
height in brick-height units, each at most 20), and `voxels`, a list of
`{ "x", "y", "z", "color" }` cells. `x` and `y` are stud coordinates, and `z`
is a plate-height coordinate (three plate levels equal one brick height).
Colors are LDraw codes from `COLOR_INFO` in `src/legolizer/catalog.py`.

```json
{
  "width": 2,
  "depth": 2,
  "height": 1,
  "voxels": [
    {"x": 0, "y": 0, "z": 0, "color": 4},
    {"x": 1, "y": 0, "z": 0, "color": 4},
    {"x": 0, "y": 1, "z": 0, "color": 4},
    {"x": 1, "y": 1, "z": 0, "color": 4}
  ]
}
```

The part catalog holds common 1×N and 2×N bricks and plates plus wide plates
up to 8×8. The size cap is 20 × 20 studs by 20 bricks tall, and the vertical
resolution is one plate.

## Render

```sh
uv run legolizer render builds/truck/model.mpd --out builds/truck/render.png
```

This uses LDView when available, including an app installed in `/Applications` or, on Windows, `Program Files\LDView`, and reads the LDraw path from pyldraw3's config. To override discovery, set `LDVIEW_BIN` to the executable inside `LDView.app`. Set `LDRAW_LIBRARY_PATH` only if the renderer should use a different library. LPub3D command line switches vary by release; to use it, set `LPUB3D_BIN` and `LPUB3D_RENDER_ARGS` to its invocation template (use `{input}` and `{output}` placeholders), or render the MPD in its GUI.

## Build guide PDF with LPub3D

LPub3D 2.4.9 can export the MPD's steps as a PDF, including a parts list for
each step. On macOS, use its native renderer:

```sh
export LDRAWDIR="/absolute/path/to/ldraw"
export LPUB3D_DISABLE_UPDATE_CHECK=1
/Applications/LPub3D.app/Contents/MacOS/LPub3D \
  --liblego --preferred-renderer native \
  --process-export --export-option pdf \
  --output-file "$PWD/builds/robot-corrected/build-guide.pdf" \
  "$PWD/builds/robot-corrected/model.mpd"
```

`LDRAWDIR` is LPub3D's library variable; use the same directory as
`LDRAW_LIBRARY_PATH`. The corrected robot exports to 15 pages. Steps currently
group parts by their bottom height, so the two legs are built side by side
before the torso connects them. This is an automatic first-pass guide; it
does not yet reorganize the model into hand-designed subassemblies.

## Implementation notes

- `.mpd` contains one assembly step per plate-height course. Open it in LPub3D, LDView, LeoCAD, or Stud.io for inspection and instruction layout.
- `parts.json` includes quantities and BrickLink catalog links based on the whitelisted LDraw part IDs. Check color availability before ordering.
- The concept image and shape program are approximate designs. The final geometry is only the official library parts emitted by the solver.
- LPub3D is an instruction authoring/rendering application; `pyldraw3` provides LDraw model construction/parsing, part catalog support, and instruction concepts. See [LPub3D](https://trevorsandy.github.io/lpub3d/) and [pyldraw3](https://github.com/hbmartin/pyldraw3).

## Regression checks

The exporter uses each official part's native X/Z footprint and top-origin Y
coordinate. Regression checks cover shape-program units, mirroring, paint and
carve, rotated footprints, mixed brick/plate heights, leg gaps, color details,
exact voxel coverage, sideways-only attachment, and preview rendering. With the library configured,
they also compare every whitelisted footprint against the official expanded geometry.

```sh
uv run python -m unittest discover -s tests -v
```

Set `LDRAW_LIBRARY_PATH` to the directory containing `parts.lst` to include the
library geometry check. The other checks run without a library or API keys.
