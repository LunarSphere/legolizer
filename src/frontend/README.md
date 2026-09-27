# Legolizer Studio

A React + Vite + Three.js frontend for inspecting an actual LDraw model, opening
its LPub3D instructions, and finding pieces to purchase. The local demo includes
the corrected 55-piece robot. All browser assets are local, including the Young Serif,
Atkinson Hyperlegible and Courier Prime fonts (bundled from `@fontsource`).

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
device camera after granting permission, with optional guidance. Both support an optional set name.
Text builds have **Add detail and color** on by default: a small model expands a short prompt
into a specific brief with a palette before design. The build card shows it under
**Expanded prompt**, along with a credited link when a Wikimedia reference photo
guided the concept image; turn the checkbox off to use your words exactly. Generation
uses paid provider calls and may take several minutes. The job tracker shows
progress through views, scene interpretation, packing, rendering, and instructions.
With Google sign-in on, **Saved sets** lists only your own sets, from any device
you sign in on. You can queue one set at a time, and other people's sets cannot
be opened, even from a saved link. **Publish to gallery** in the build card shares
a set's name, description, 3D model, parts list and instructions with everyone,
under your first name; **Remove from gallery** takes it down (links already handed
out stop working within 15 minutes). The **Gallery** tab lists published sets for
every visitor, signed in or not, and **Copy link** gives a `?build=<id>` link that
opens the set directly. Other people's sets open read-only: no Select or refine.
When ready, the new set appears in **Saved sets** and opens in the viewer. Click
any saved set to switch the viewer; the last selected set is remembered by this
browser. Opening a set plays a ~2.5 s assembly animation (bricks drop in layer by
layer, following the MPD steps, farthest from the camera first); it is skipped when the OS requests reduced
motion and on a plain page reload. The **Layer** slider on the left of the viewer
then steps through the build: sliding up drops the new layers in, sliding down
removes them instantly, and your camera view is kept. The play/pause button under
the slider pauses auto-play, finishes the build from the current layer, or (at the
top layer) replays the whole assembly.

### Saved data and failures

Builds, metadata, artifacts, and job history live under `builds/studio/` by default.
Set `LEGOLIZER_DATA_DIR` on the server to choose another persistent directory.
These files are ignored by Git; back up this directory to keep your library.
The bundled robot demo is copied on first startup but kept out of Saved sets and the
Gallery, and it is never opened by default. The studio opens your newest saved set, or
the newest gallery set when you have none.
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
- **View:** show/hide the model, piece outlines, and automatic rotation. The grid
  is always on.
- **Rename:** owners can rename a set from the build panel (also while generation
  is paused).
- **Build instructions (pdf):** open the actual LPub3D PDF in a new tab.
- **Parts list:** show quantities by part and color, with BrickLink links.
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
| GET | `/session` | Sign-in state, auth mode, and the Google client ID |
| POST | `/session` | Exchange a Google ID token for a session cookie |
| DELETE | `/session` | Sign out |
| GET | `/builds` | Your completed builds, paginated (every build with auth off) |
| GET | `/gallery` | Published builds, newest first (public) |
| PUT | `/builds/{buildId}/visibility` | Publish to or remove from the gallery (owner only) |
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

Admins listed in the server's `LEGOLIZER_ADMIN_EMAILS` see a **Pause generation**
button at the top of the studio. While paused, every visitor sees "Temporary
generation pause to conserve compute" and the Generate and Suggest size buttons are
disabled; **Resume generation** turns it back on.

When the server sets `LEGOLIZER_AUTH=google`, signed-out visitors see a
**Sign in with Google** button instead of the generation form. The studio gets
the OAuth client ID from `GET /session`, loads Google Identity Services, and
posts the returned ID token to `POST /session`. The server answers with an
HttpOnly session cookie, so the browser never holds a token. The cookie is only
sent to the same origin, so sign-in needs the default proxied `/api/v1` base.
Google only accepts registered origins, so test sign-in locally on
`http://localhost:5173` (see [instructions.md](../../instructions.md) step 7).

Assets use official LDraw geometry and retain embedded part license headers.
The server only serves an allowlist of artifact filenames for completed builds.
Locally the server binds only to loopback and restricts browser origins to
localhost/127.0.0.1 ports 5173 and 8000. The demo deployment (root `vercel.json`,
see [src/infra/README.md](../infra/README.md)) serves this SPA and the same API
from one Vercel origin, with generation on an on-demand AWS worker. There are no
user accounts or rate limits: anyone with the URL can queue paid provider calls.

## Image → LEGO

Upload or capture one PNG, JPEG, or WebP still image, up to 3 MiB, with each dimension between
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
