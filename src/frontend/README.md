# Legolizer Studio

A React + Vite + Three.js frontend for inspecting an actual LDraw model, opening
its LPub3D instructions, and finding pieces to purchase. The local demo includes
the corrected 55-piece robot. All browser assets are local except the optional
Google Fonts stylesheet (system sans-serif fonts are the fallback).

## Run locally

Install the Python dependencies with `uv sync` at the repository root and
Node.js 22.12+ with npm. Start the API in one terminal from the repository root:

```sh
source ~/.zshrc
export LDRAW_LIBRARY_PATH="/absolute/path/to/ldraw"
uv run python -m legolizer.server
```

Generation needs a design-model key: `ANTHROPIC_API_KEY` (or `CLAUDE_API_KEY`),
`OPENAI_API_KEY`, or `GROK_API_KEY` with `SCENE_PROVIDER=grok`. Text generation also
draws a concept image with `OPENAI_API_KEY`, or `GROK_API_KEY` with
`IMAGE_PROVIDER=grok`, so Grok alone can run everything. Both need
the official LDraw library with `parts.lst`, LDView, and LPub3D to generate sets.
See [installation instructions](../../instructions.md). Keys are only used on
the server, never in browser code. It binds to `127.0.0.1:8000`.

In a second terminal:

```sh
cd src/frontend
npm ci
npm run dev -- --port 5173 --strictPort
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to the Python server. On the
original development machine, prepend the project-local Node installation to
PATH from the repository root if needed:

```sh
export PATH="$PWD/.tools/node-v22.23.3-darwin-arm64/bin:$PATH"
```

Choose **Text → LEGO** to describe a small brick sculpture, or **Image → LEGO**
to upload a reference image (desktop file picker or mobile gallery) or take a photo with the
device camera after granting permission, with optional guidance. Both support an optional set name. Generation
uses paid provider calls and may take several minutes. The job tracker shows
progress through views, scene interpretation, packing, rendering, and instructions.
When ready, the new set appears in **Saved sets** and opens in the viewer. Click
any saved set to switch the viewer; the last selected set is remembered by this
browser. Opening a set plays a ~2.5 s assembly animation (bricks drop in layer by
layer, following the MPD steps, far corner first); it is skipped when the OS requests reduced
motion and on a plain page reload. The **Layer** slider on the left of the viewer
then steps through the build: sliding up drops the new layers in, sliding down
removes them instantly, and your camera view is kept.

### Saved data and failures

Builds, metadata, artifacts, and job history live under `builds/studio/` by default.
Set `LEGOLIZER_DATA_DIR` on the server to choose another persistent directory.
These files are ignored by Git; back up this directory to keep your library.
The existing robot is imported from the bundled demo on first startup.
Each generation receives a unique directory. Existing sets are never overwritten.
Refreshes and restarts keep completed sets. Interrupted jobs are marked failed
rather than replaying paid requests. Failed attempts keep their prompt and partial
artifacts; **Use these inputs again** lets you edit and submit a new attempt.
Image retries ask you to choose the reference image again. The original upload is
kept privately as `source.png`, `source.jpg`, or `source.webp` in the job folder.
The server processes one generation at a time and accepts up to three pending jobs.

For the static, view-only robot demo without a backend, set `VITE_DEMO=true` in
`.env.local` and restart Vite. Production assets compile with `npm run build`;
`npm run preview` serves them with the same local API proxy.

## Controls

- **Orbit:** left-drag to rotate around the model; scroll or pinch to zoom.
- **Pan:** select Pan and drag to move the view. Right-drag also pans in Orbit.
- **AR:** open augmented reality on a supported phone (WebXR immersive AR, typically
  Chrome on Android over HTTPS or localhost). Point at a desk or table until the
  placement ring appears, tap to place, then use Rotate / Pan and pinch to
  scale. Unsupported browsers show a clear message and a back button; closing AR
  returns to the normal studio viewer without interrupting generate, orbit, or
  parts flows. The studio WebGL loop pauses while AR is open.
- **Move model:** expand this section for X, Y, and Z position sliders. One stud
  is 20 LDraw units. These are display transforms; downloaded geometry stays original.
- **Reset:** restore the camera and model position.
- **Checkboxes:** show/hide the model, grid, outlines, and automatic rotation.
- **Instructions:** open the actual LPub3D PDF in a new tab.
- **Find your pieces:** show quantities by part and color, with BrickLink links.
  These links open catalog pages, not a pre-filled cart or guaranteed inventory.
- **Download:** save the original MPD or the parts JSON.

The renderer uses Three.js [LDrawLoader](https://threejs.org/docs/pages/LDrawLoader.html)
with embedded official part geometry. It does not reconstruct bricks as boxes.
The model uses LDraw's original materials and is rotated to Three.js's Y-up space.
AR loads the same packed MPD and local `LDConfig.ldr` colors; it never fetches a
remote parts library.

## Refresh the demo

From the repository root, after generating a model and PDF:

```sh
uv run python src/frontend/scripts/prepare_demo.py \
  --build builds/robot-corrected --library /absolute/path/to/ldraw
```

The source directory must contain `model.mpd`, `parts.json`, `build-guide.pdf`,
and `render.png`. The script recursively embeds the referenced official parts
and primitives in `public/demo/packed.mpd`, retains their license headers,
and copies the accompanying library license files. Demo title and ID are
currently set for Little Bot in this script.

## REST API

The implemented local contract is [api/openapi.json](api/openapi.json), OpenAPI 3.1.

| Method | Path (under `/api/v1`) | Purpose |
| --- | --- | --- |
| GET | `/builds` | Paginated completed builds |
| GET | `/builds/{buildId}` | Ready model metadata and asset URLs |
| GET | `/builds/{buildId}/parts` | Parts quantities, colors, purchase links |
| POST | `/builds` | Submit a description and optional name; returns HTTP 202 |
| GET | `/jobs` | Persistent job history for refresh recovery |
| GET | `/jobs/{jobId}` | Generation progress and completion |
| GET | `/assets/{buildId}/{filename}` | Published build artifacts |

POST requires a unique `Idempotency-Key` header. Retrying a request with the same
key and body returns the same job; changing the body returns 409. The frontend
preserves this key after a network error. The current pipeline uses its eight-color
palette; the optional `maxColors` field only accepts 8.

Copy `.env.example` to `.env.local` to customize the API base URL. The default
`/api/v1` uses Vite's proxy. `VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1` calls
the API directly. Restart Vite after changes. `src/api.js` isolates all requests.
Never put provider keys in `VITE_*` values: those values are public browser code.

Assets use official LDraw geometry and retain embedded part license headers.
The server only serves an allowlist of artifact filenames for completed builds.
This server is for a trusted local macOS workspace; it binds only to loopback and
restricts browser origins to localhost/127.0.0.1 ports 5173 and 8000. It does not
implement user accounts. Add authentication, authorization, and a durable worker
service before deploying it as a shared remote application.

## Image → LEGO

Upload or capture one PNG, JPEG, or WebP still image, up to 4 MiB, with each dimension between
32 and 4096 pixels. On phones, **Choose from gallery** opens the photo library and **Take photo**
requests camera permission for an in-app capture; on desktop, **Upload image** opens the file
picker (webcam capture is also available when a camera is present). The browser previews the
image and checks dimensions; the server
validates file contents, type, size, dimensions, and decodability before accepting
a job. Filenames supplied by the browser are not used on disk.

Image jobs go directly to Claude for scene interpretation, then use the same
voxel solver, official LDraw parts, render, PDF export, and persistent library
as text jobs. A single view cannot determine hidden surfaces exactly: the model
infers conservative depth and records assumptions in `scene.json`.

`POST /api/v1/builds` continues to accept text requests. For image requests send:

```json
{
  "name": "My image build",
  "description": "Focus on the vehicle, ignore the background",
  "image": { "mediaType": "image/png", "data": "BASE64_IMAGE_BYTES" }
}
```

`description` and `name` are optional for image requests. Use raw base64 without
the `data:image/...` prefix. Total request size is limited to 6 MiB. The source
image is stored locally and sent to Claude only when Generate is submitted.
