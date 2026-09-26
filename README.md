# Legolizer

Turn a short object description into a voxelized LEGO-style model, a stepped LDraw MPD, a parts list, and a render. The proof of concept uses only a small whitelist of official LDraw bricks, plates, round plates and tiles, slopes, arches, and curved corner bricks. It does not create or approximate part geometry.

## Local React frontend

Start the local API from the repository root with `uv run python -m legolizer.server`
(it reads the same `.env` as the CLI, and needs LDView and LPub3D installed).
Then start the frontend below.

The viewer in [`src/frontend`](src/frontend/README.md) includes the corrected
robot demo, orbit/pan/zoom controls, model position sliders, visibility settings,
PDF instructions, and a color-aware parts purchase list. Generate from text or upload an image (PNG/JPEG/WebP, up to 3 MB), then switch
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
# Optional: draw concept images with Grok Imagine instead of OpenAI
$env:IMAGE_PROVIDER = "grok"
$env:GROK_API_KEY = "..."
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
export IMAGE_PROVIDER="grok"  # optional: Grok Imagine concept images
export GROK_API_KEY="..."
export LPUB3D_BIN="/Applications/LPub3D.app/Contents/MacOS/LPub3D"
export LDVIEW_BIN="/Applications/LDView.app/Contents/MacOS/LDView"
export LDRAW_LIBRARY_PATH="/path/to/ldraw"
```

To use an existing LDraw library, set its path in pyldraw3's `config.yml`; inspect the active settings with `uv run ldraw config`.

API keys are needed only for live generation; calls may incur provider charges.

## How it works

1. **Concept image (optional).** An image model draws one 3/4 picture of the
   object as a brick model: OpenAI's `OPENAI_IMAGE_MODEL` by default, or xAI's
   Grok Imagine (`GROK_IMAGE_MODEL`, default `grok-imagine-image`, using
   `GROK_API_KEY`) when `IMAGE_PROVIDER=grok`. It guides colors, proportions and which features
   matter. It is never measured, so its inaccuracies cannot become geometry.
2. **Shape program.** A vision model (Claude if `ANTHROPIC_API_KEY` is set,
   otherwise OpenAI's `OPENAI_SCENE_MODEL`, default `gpt-5`; override with
   `SCENE_PROVIDER`) writes the object as an ordered list of 3D primitives:
   boxes, ellipsoids and cylinders with taper, left/right mirroring, and
   solid/paint/carve modes, in uniform stud units. Responses are forced to a
   JSON schema. An explicit `pieces` list selects specialty parts, their colors and rotations.
   The design prompt lists the official rectangular inventory that the packer
   selects from automatically, and explains when each specialty part helps.
   This program is the single 3D source of truth.
3. **Voxelize.** Python converts the program to 1 stud × 1 stud × 1 plate
   cells, reporting parts that were clipped, covered, or had no effect. Specialty
   pieces reserve their bounding boxes and replace the voxels inside them.
4. **Pack.** The solver covers the cells with official bricks and plates,
   staggers seams across restarts, and favors mirrored placements when voxel
   occupancy and colors are left-right symmetric. Symmetric models may use one
   extra packing attempt to improve the mirrored layout. When stepped surfaces
   leave bricks touching only sideways, a bounded local repair retile uses plates
   across their height levels while preserving the occupied cells and visible colors.
   Alternate plate courses start at an offset to bond wide base sections across seams.
   It repairs remaining pieces that only touch sideways,
   and lets hidden interior cells take any color. Explicit pieces remain fixed;
   connections use their actual stud and bottom-socket positions. It reports every piece not
   attached to the main build through studs, named by the program part it came
   from.
5. **Review.** Front, right, top and 3/4 voxel previews (or an official LDraw
   assembly render when specialty pieces are present), plus that build report, go back to the vision model. It critiques them against the
   description and concept and returns a corrected program. This repeats for
   `--iterations` rounds (default 2), and the best round is kept: fewest
   unattached pieces, then the latest.
   Invalid programs, including overlapping explicit pieces, receive validation
   feedback within this same review budget. Each `program.vN.json` is saved
   before validation so rejected designs can be inspected. With no reviews left,
   the best valid round is retained, or the build fails if there was none.

Specialty builds use LDView (or a configured LPub3D renderer) for their preview,
so the reviewer sees the real curves and openings. They require a renderer and
the official LDraw library even when no separate final PNG is requested.

Generated programs can receive up to eight short support columns per review round
under disconnected specialty pieces. Each column spans at most six plate levels
and joins an existing stud in the main assembly to a real bottom socket; arch
openings and tile tops are respected. Supports are kept only if connectivity
improves and are saved in `program.json` and noted in `design.log`. Explicit CLI
`--program` and `--fixture-json` inputs retain their geometry.

After review, generated builds may drop small disconnected fragments from the
best round: at most eight pieces, 5% of all pieces, and 2% of occupied envelope
volume. All three limits must hold, and the remainder must be grounded and
stud-connected. The retained placements stay unchanged; no extra packing or LLM
pass runs. `program.before-pruning.json` preserves the source, `pruning.json`
lists removed pieces, and `design.log` records the change. The final program,
preview, parts list, model, and instructions reflect the removal. Larger detached
sections still fail. Overlapping pieces must pass validation before this step;
pruning does not bypass that check.

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

### Specialty pieces and colors

The first five additions are drawn from the categories in the
[Brick Architect parts guide](https://brickarchitect.com/parts/most-common).
Only official LDraw files supply the rendered geometry:

| Part | LDraw ID | Native X × Y footprint | Height in plates |
| --- | --- | --- | --- |
| Round plate 1×1 | [6141](https://library.ldraw.org/library/official/parts/6141.dat) (BrickLink 4073) | 1×1 | 1 |
| Round tile 1×1 | [98138](https://library.ldraw.org/library/official/parts/98138.dat) | 1×1 | 1 |
| Slope 45° 1×2 | [3040b](https://library.ldraw.org/library/official/parts/3040b.dat) (BrickLink 3040) | 1×2 | 3 |
| Arch 1×4 | [3659](https://library.ldraw.org/library/official/parts/3659.dat) | 4×1 | 3 |
| Curved corner brick 2×2 | [3063b](https://library.ldraw.org/library/official/parts/3063b.dat) (BrickLink 3063) | 2×2 | 3 |

Add a `pieces` array alongside a shape program's `parts`. For example:

```json
"pieces": [{"part": "3659", "x": 2, "y": 2, "z": 8, "color": 15, "rotation": 0}]
```

Here `x` and `y` locate the minimum corner of the rotated footprint in integer
studs. **`z` is an integer plate level**, unlike the primitive coordinates in
stud units: `z: 8` places the bottom 3.2 studs above the ground. Rotations are
0, 90, 180 or 270 degrees; 90 maps native +X toward -Y. Pieces apply after all
primitives. Their full bounding boxes replace underlying voxels and cannot
overlap each other, even in an arch opening or a curved corner's empty space.
This conservative reservation prevents collisions; those empty areas remain
empty in the exported geometry. The packer preserves these chosen pieces and
fills the remaining voxels with rectangular bricks and plates. It does not
infer specialty pieces from old voxel fixtures.

Tiles have no top studs, slopes have one high stud, arches connect underneath
at their two ends, and curved corners connect at their two diagonal studs.
Only upright placements and vertical stud connections are supported in this
first set. Saved programs without `pieces` continue to work.

The designer uses **15 common colors**: black (0), blue (1), green (2), red (4),
yellow (14), white (15), tan (19), orange (25), lime (27), dark tan (28), bright
pink (29), reddish brown (70), light bluish gray (71), dark bluish gray (72),
and dark blue (272). Previously accepted colors remain valid in saved files.
Part/color availability is not an inventory guarantee; check before ordering.

Try the small garden gate, which uses all five new part types without API calls:

```sh
uv run legolizer build "garden gate" --program examples/garden-gate.json --out builds/garden-gate
```

Its `preview.png` renders the official assembly. See `model.mpd` and `parts.json`
for the model and shopping list.

### Voxel fixtures

`--fixture-json` takes `width`, `depth`, `height` (width/depth in studs;
height in brick-height units, each at most 20), and `voxels`, a list of
`{ "x", "y", "z", "color" }` cells. `x` and `y` are stud coordinates, and `z`
is a plate-height coordinate (three plate levels equal one brick height).
Colors are LDraw codes from `COLOR_INFO` in `src/legolizer/catalog.py`.
Fixtures may also contain the same `pieces` array; their voxels must exclude
reserved piece envelopes, and dimensions must contain both voxels and pieces.

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
up to 8×8, plus the five explicit specialty parts above. The size cap is 20 × 20 studs by 20 bricks tall, and the vertical
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
coordinate, including per-part native offsets and all four upright rotations. Regression checks cover shape-program units, mirroring, paint and
carve, rotated footprints, mixed brick/plate heights, leg gaps, color details,
exact voxel coverage, sideways-only attachment, and preview rendering. With the library configured,
they also compare every whitelisted footprint against the official expanded geometry.

```sh
uv run python -m unittest discover -s tests -v
```

Set `LDRAW_LIBRARY_PATH` to the directory containing `parts.lst` to include the
library geometry check. The other checks run without a library or API keys.

Saved shape programs in `tests/fixtures/` exercise real garden gate, seaside
market, Burj Khalifa, and Hagia Sophia generations. Their regression checks
require complete coverage without overlap, preserved visible colors and fixed
pieces, and stud connectivity. The original failing Hagia Sophia remains in the
corpus alongside the repaired design; tests also verify that unsupported gaps,
sideways contact, and tile tops cannot be accepted as valid attachments.
Successful live trial programs extend the same corpus. A failed lighthouse
program checks that decimal rounding at adjoining primitive faces cannot remove
an entire plate course and disconnect the lantern.

Run just this offline corpus with:

```sh
uv run python -m unittest discover -s tests -p test_generation_regressions.py -v
```

Live prompt trials run separately through the local studio/API and use provider
credits. Keep their saved programs and logs when diagnosing failures; add a
reproducible failing program and its expected outcome to the offline corpus.
Passing these tests protects known cases, while every new generation still goes
through the final connectivity check. Connectivity alone does not measure visual
similarity or certify physical load-bearing strength.
