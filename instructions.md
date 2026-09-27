# Software installation

These instructions cover the macOS setup used for this proof of concept, with
Windows notes in each step. Run project commands from the repository root. The
working setup used Python 3.13, LDView 4.7, and LPub3D 2.4.9.86 on Apple Silicon.
The project requires Python 3.12 or newer.

| Software | Purpose |
| --- | --- |
| uv | Install Python and manage the project's locked dependencies |
| pyldraw3 | Download and index official LDraw parts; parse and validate models |
| Official LDraw library | Existing brick and plate geometry |
| LDView | Render the finished model to PNG |
| LPub3D | Export assembly steps and per-step parts lists to PDF |
| Docker (optional) | Run the same generation container used in the AWS deployment ([step 8](#8-run-the-generation-container-locally)) |
| AWS CLI v2, Vercel account (optional) | Deploy the worker with AWS CDK and the studio + API to Vercel ([step 9](#9-deploy-to-aws-and-vercel)) |

Steps 1–7 set up the native macOS/Windows workflow. The Docker image installs
the same pieces on Ubuntu 22.04 (uv, Python 3.13 with the locked dependencies,
the `ldraw download` library, and LPub3D 2.4.9.86 with its bundled LDView), so
you can skip steps 2–4 when you only run the containers.

## 1. Install uv and project dependencies

Install uv using its [official installer](https://docs.astral.sh/uv/getting-started/installation/):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv python install 3.13
uv sync --locked --python 3.13
```

On Windows, in PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# Reopen the terminal so uv is on PATH, then:
uv python install 3.13
uv sync --locked --python 3.13
```

`uv sync` installs this project, pyldraw3, and the OpenAI and Anthropic SDKs into
`.venv`. Use `uv run` for project commands; a separate global pip installation
is unnecessary.

## 2. Download and configure the official LDraw library

Use the CLI provided by [pyldraw3](https://github.com/hbmartin/pyldraw3/):

```sh
uv run ldraw download --yes
uv run ldraw generate --yes
uv run ldraw config
```

On Windows, run `$env:PYTHONUTF8 = "1"` in the same PowerShell window first.
Without it, pyldraw3 fails with `'charmap' codec can't encode character`
while writing `parts.lst`.

The download command saves the library location in pyldraw3's configuration.
The generate command prepares its part index. Set the following variables to
the extracted `ldraw` directory, which contains `parts/`, `p/`, `LDConfig.ldr`,
and `parts.lst`. If the configured path ends in `complete`, its `ldraw`
subdirectory is the directory to use here.

```sh
export LDRAW_LIBRARY_PATH="/absolute/path/to/complete/ldraw"
export LDRAWDIR="$LDRAW_LIBRARY_PATH"
```

On Windows, put these in `.env` (see step 5) or set them in PowerShell:

```powershell
$env:LDRAW_LIBRARY_PATH = "C:\Users\you\AppData\Local\pyldraw3\pyldraw3\Cache\complete\ldraw"
$env:LDRAWDIR = $env:LDRAW_LIBRARY_PATH
```

Replace the example path with your actual installation. `LDRAW_LIBRARY_PATH`
is used by this project's validation and PNG rendering; `LDRAWDIR` is used by
LPub3D. Use a persistent directory rather than a temporary download folder.

## 3. Install LDView

1. Download the macOS disk image from the official
   [LDView downloads page](https://tcobbs.github.io/ldview/Downloads.html).
2. Open the `.dmg` and copy `LDView.app` to `/Applications`.
3. Open LDView once. If asked for the LDraw library, select the directory from
   step 2 above.

On Windows, run the LDView installer from the same page. The project
automatically finds `LDView64.exe` or `LDView.exe` in `Program Files\LDView`
or on `PATH`.

The project automatically finds `/Applications/LDView.app`. You can also set
the executable explicitly:

```sh
export LDVIEW_BIN="/Applications/LDView.app/Contents/MacOS/LDView"
```

```powershell
$env:LDVIEW_BIN = "C:\Program Files\LDView\LDView64.exe"
```

## 4. Install LPub3D

1. Open the official [LPub3D releases](https://github.com/trevorsandy/lpub3d/releases).
2. Download the macOS `.dmg` matching your processor and supported macOS
   version: ARM64 for Apple Silicon, or an Intel build for an Intel Mac.
3. Open the disk image and copy `LPub3D.app` to `/Applications`.
4. Open LPub3D, select the LEGO parts library if prompted, and use the
   **Native** renderer for instruction export.

```sh
export LPUB3D_BIN="/Applications/LPub3D.app/Contents/MacOS/LPub3D"
export LPUB3D_DISABLE_UPDATE_CHECK=1
```

On Windows, run the `.exe` installer from the releases page, then:

```powershell
$env:LPUB3D_BIN = "C:\Program Files\LPub3D\LPub3D.exe"
$env:LPUB3D_DISABLE_UPDATE_CHECK = "1"
```

The Native renderer successfully generated this project's robot guide.
LPub3D also bundles other rendering tools; their additional dependencies are
listed in its [documentation](https://trevorsandy.github.io/lpub3d/), under
“LPub3D macOS Library Dependencies.” Those tools are not needed for the Native
PDF command below.

## 5. Configure API credentials

Live generation needs a key for the design model, which writes and reviews the
shape program. When `ANTHROPIC_API_KEY` is set, Claude does it; otherwise an
OpenAI vision model (`OPENAI_SCENE_MODEL`, default `gpt-6-sol`), or Grok
(`GROK_SCENE_MODEL`, default `grok-4.20-0309-reasoning`) when `GROK_API_KEY` is
the only key. Set `SCENE_PROVIDER` to `openai`, `anthropic` or `grok` to choose
explicitly. Quick classification calls (stylize helpers such as size estimate)
use the provider's small model; set `FAST_PROVIDER` to route them (unset prefers
Grok when `GROK_API_KEY` is set, otherwise the design provider).

Text builds first draw a concept image with OpenAI Images. To use xAI's Grok
Imagine instead, set `IMAGE_PROVIDER=grok` and `GROK_API_KEY` (from
[console.x.ai](https://console.x.ai)); `GROK_IMAGE_MODEL` defaults to
`grok-imagine-image`. With `IMAGE_PROVIDER=grok` and `SCENE_PROVIDER=grok`,
`GROK_API_KEY` is the only key you need. The AWS worker image defaults
`IMAGE_PROVIDER=grok` via `src/infra/container.env`.

Named real-world subjects may fetch a free Wikipedia lead photo for the concept
step (`REFERENCE_IMAGES=wikimedia` by default; set `off` to disable).

```sh
export OPENAI_API_KEY="your-openai-api-key"
export ANTHROPIC_API_KEY="your-anthropic-api-key"
```

On Windows PowerShell, use:

```powershell
$env:OPENAI_API_KEY = "your-openai-api-key"
$env:ANTHROPIC_API_KEY = "your-anthropic-api-key"
```

For Command Prompt, use `set OPENAI_API_KEY=your-openai-api-key` and
`set ANTHROPIC_API_KEY=your-anthropic-api-key`. These commands apply to the
current terminal. For a persistent cross-platform setup, copy `.env.example`
to `.env` and replace the placeholders. The `legolizer` command loads that file
at startup and does not replace variables already present in the environment.

The project also accepts `CLAUDE_API_KEY` as a fallback when
`ANTHROPIC_API_KEY` is unset. On macOS/Linux, save exports in `~/.zshrc` if
you want them available in new terminals, then reload it:

```sh
source ~/.zshrc
```

On Windows, `.env` is the simplest persistent option. Alternatively,
`setx OPENAI_API_KEY "your-openai-api-key"` stores a user variable that new
terminals (not the current one) will see.

Keep actual credentials out of the repository. `.env` is intended for local
use and should not be committed. Existing MPD files can be rendered and
exported without API keys.

## 6. Generate a model, render, and build guide

Generate a model (makes paid API calls):

```sh
uv run legolizer build "a small red and blue toy robot with a yellow head" \
  --out builds/robot
```

Render it with LDView:

```sh
uv run legolizer render builds/robot/model.mpd --out builds/robot/render.png
```

Export instructions with LPub3D:

```sh
"$LPUB3D_BIN" \
  --liblego --preferred-renderer native \
  --process-export --export-option pdf \
  --output-file "$PWD/builds/robot/build-guide.pdf" \
  "$PWD/builds/robot/model.mpd"
```

On Windows (PowerShell):

```powershell
& $env:LPUB3D_BIN `
  --liblego --preferred-renderer native `
  --process-export --export-option pdf `
  --output-file "$PWD\builds\robot\build-guide.pdf" `
  "$PWD\builds\robot\model.mpd"
```

Use absolute paths for LPub3D's input and output. To export the existing
corrected robot, replace `builds/robot` with `builds/robot-corrected` in that
command. Generated files under `builds/` are local artifacts and may not be
present in a fresh checkout.

## Troubleshooting

- **`uv` not found:** reopen your terminal or source `$HOME/.local/bin/env`.
- **Windows: `$env:...` values vanish:** they last only for the current
  PowerShell window. Use `.env` for a persistent setup.
- **Parts library or `parts.lst` missing:** run the download and generate
  commands, then check that both library variables point to the extracted
  `ldraw` directory.
- **Renderer executable not found:** copy the app into `/Applications` or
  set its executable variable to the actual binary inside the app bundle.
- **LPub3D reports missing libraries for LDView or POV-Ray:** select Native
  for PDF export. PNG rendering uses the separately installed LDView app.
- **Different LPub3D release:** run `"$LPUB3D_BIN" --help` to inspect its
  supported export flags.

For the pipeline, input format, and output details, see [README.md](README.md).

## 7. Run the React frontend locally

Install Node.js 22.12+ with npm from the [official Node.js download page](https://nodejs.org/en/download).
From the repository root:

```sh
cd src/frontend
npm ci
npm run dev -- --port 5173 --strictPort
```

Start the generation API in a separate terminal from the repository root:

```sh
uv run python -m legolizer.server
```

The server reads `.env` like the CLI, so keys and `LDRAW_LIBRARY_PATH` set
there apply. It also needs LDView and LPub3D (steps 3 and 4), because every
saved set includes a render and a PDF guide. On Windows, run the same commands
in two PowerShell windows.

Open **http://127.0.0.1:5173**. Choose Text → LEGO to enter a prompt, or Image → LEGO to upload a PNG, JPEG, or
WebP image up to 3 MB (or use the device camera on mobile) with optional guidance.
Text builds can set a target longest side (16–32 studs in steps of 4) or leave
**Auto** for the stylizer. Both modes save new sets. Choose previous builds from
Saved sets. To change part of a set, choose **Select** under the viewer, click
the bricks to change (only they and one brick around each can change; select
none to edit the whole model), and describe the change. The refined set is saved
separately. Provider keys and installed renderers are used by the Python server.
Completed sets persist in `builds/studio/`; back up this Git-ignored directory.
For a view-only robot demo without the server, set `VITE_DEMO=true` in
`src/frontend/.env.local` and restart Vite. Python dependencies still use uv;
frontend dependencies use npm and `package-lock.json`.

The local server has no accounts by default: every visitor is the same local
user. To try Google sign-in locally, create a Web OAuth client (see step 9) with
`http://localhost` and `http://localhost:5173` as authorized JavaScript origins,
set `LEGOLIZER_AUTH=google` and `LEGOLIZER_GOOGLE_CLIENT_ID` in `.env`, restart
the server, and open **http://localhost:5173**. Signed-in users get a personal
library, one queued build at a time, and optional **Publish to gallery**. Point
Google's consent-screen privacy policy URL at your deployed
`/privacy.html` (see `src/frontend/public/privacy.html`).

On the original development machine, Node was installed locally under `.tools`.
If `npm` is not on PATH, run this from the repository root before the commands above:

```sh
export PATH="$PWD/.tools/node-v22.23.3-darwin-arm64/bin:$PATH"
```

See the [frontend README](src/frontend/README.md) for refreshing demo assets and
configuring the local backend using the [REST API specification](src/frontend/api/openapi.json).

Both modes use the design-and-review pipeline described in the README. Text
jobs stylize the prompt (unless disabled), may fetch a Wikipedia reference photo,
then generate a concept image. Image uploads are validated with Pillow and used
as the concept image instead, so they skip provider image generation. Each job's
program, preview renders and `design.log` are saved in
`builds/studio/models/<job id>/`.

## 8. Run the generation container locally

Install [Docker Desktop](https://docs.docker.com/desktop/) (or Docker Engine
with Compose v2) and give it at least 4 GB of memory. The image is
`linux/amd64`, the architecture Fargate runs; Apple Silicon emulates it, which
is slower but produces the same files.

One command builds the image and runs it the way it runs in production:
jobs go through the shared DynamoDB queue and finished files go to S3, with
DynamoDB Local and S3Mock standing in for the real services.

```sh
src/infra/scripts/validate-local.sh          # add --keep to leave the stack running
```

The smoke test checks that the container has LDView, LPub3D, and the LDraw
library. It fills the queue with offline shape-program jobs, which need no
provider keys, and confirms that the next submission gets 429. It also
confirms that jobs run one at a time while the rest wait, and that every build
serves a PNG render, a PDF guide, and an MPD through presigned S3 links. On
success it records the image ID in `builds/infra/validated.json`; `deploy.sh`
refuses to push any other image. Add `--live` to also run one paid text job.
That requires provider keys in `.env` (or your shell), which compose passes to
the container.

With `--keep`, the API listens on http://127.0.0.1:8000, and the Vite dev
server's `/api` proxy reaches it unchanged. In production the same request
handler runs as a Vercel function (`api/index.py`), and the container only
runs jobs. Useful commands:

```sh
docker compose -f src/infra/docker/compose.yaml logs -f api
docker compose -f src/infra/docker/compose.yaml down
```

### Runtime configuration

Shared values live in `src/infra/container.env`. Compose, the Fargate task
definition, and the Vercel function (via `deploy-frontend.sh`) all read it, so
every environment gets the same settings. Renderer paths are fixed in the image.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LEGOLIZER_BACKEND` | `local` (`aws` in containers) | `aws` keeps jobs in DynamoDB and assets in S3 |
| `LEGOLIZER_BUCKET`, `LEGOLIZER_TABLE` | — | Required for `aws`; set by compose, CDK, and `deploy-frontend.sh` |
| `LEGOLIZER_WORKERS` | `1` | Jobs a worker container runs at once |
| `LEGOLIZER_MAX_PENDING` | `3` (`4` in containers) | Queued + running jobs before new submissions get 429 |
| `LEGOLIZER_MAX_PENDING_PER_USER` | `1` | With Google sign-in, queued + running jobs one user may have |
| `LEGOLIZER_STALE_SECONDS` | `300` | A running job with no heartbeat for this long is failed |
| `LEGOLIZER_POLL_SECONDS` | `3` | Idle queue polling interval |
| `LEGOLIZER_IDLE_EXIT_SECONDS` | `0` (never) | Worker exits after this long without jobs (`900` on Fargate) |
| `LEGOLIZER_PROGRAM_JOBS` | off (`1` in containers) | Accept offline shape-program jobs (used by the smoke test) |
| `LEGOLIZER_ALLOWED_ORIGINS`, `LEGOLIZER_ALLOWED_HOSTS` | loopback (plus the Vercel deployment's own URLs) | Extra browser origins / `Host` headers (comma-separated, `*` wildcards) |
| `LEGOLIZER_AUTH` | `off` (`google` from `deploy-frontend.sh`) | API only. `google` requires Google sign-in to generate; `off` treats every visitor as one local user |
| `LEGOLIZER_GOOGLE_CLIENT_ID` | — | API only. Web OAuth client ID for Google sign-in; public, but set per environment rather than in `container.env` |
| `LEGOLIZER_WORKER_CLUSTER`, `_TASK_DEFINITION`, `_SUBNETS`, `_SECURITY_GROUPS` | — | API only: start the Fargate worker when jobs are queued |
| `LEGOLIZER_AWS_ACCESS_KEY_ID`, `_SECRET_ACCESS_KEY`, `_REGION` | default AWS chain | API credentials on Vercel, which reserves the `AWS_*` names |
| `LEGOLIZER_S3_PUBLIC_ENDPOINT` | — | Endpoint for presigned links when S3 has a container-only name (compose) |
| `LEGOLIZER_HOST`, `LEGOLIZER_PORT` | `127.0.0.1`, `8000` | Bind address (`0.0.0.0` in the image) |
| `IMAGE_PROVIDER` | `openai` (`grok` in containers) | Concept image model; `grok` uses Grok Imagine |
| `OPENAI_API_KEY`, `GROK_API_KEY` | — | Provider keys (step 5); Secrets Manager on the worker. `ANTHROPIC_API_KEY` works locally but is not deployed |

## 9. Deploy to AWS and Vercel

Deploy only after step 8 passes. You need AWS credentials (`aws login` or a
profile) for an account where CDK is bootstrapped (`npx cdk bootstrap`), and
`npx vercel login`. The studio and API run on Vercel (Hobby is enough). AWS
runs one on-demand Fargate task (4 vCPU, 12 GB) with no public IPv4 address,
no load balancer, and no NAT gateway. It starts when a job is queued, which
takes about 1–2 minutes, and stops after 15 idle minutes, so you pay only
while it works.

Visitors sign in with Google before they can generate. Before the first
deploy, create a **Web application** OAuth client in the Google Cloud console
(APIs & Services → Credentials) and configure its consent screen with the app
name, a support email, and a privacy policy URL (use the Studio's
`https://<your-domain>/privacy.html`). The `openid email profile` scopes that
sign-in uses do not need Google verification. Add the production origin (for
example `https://legolizer.vercel.app`, or your custom domain) under
**Authorized JavaScript origins**. Google does not accept wildcards, so Vercel
preview URLs cannot sign in. Export the client ID before running
`deploy-frontend.sh`, or set `LEGOLIZER_AUTH=off` to deploy one shared
workspace without accounts:

```sh
export LEGOLIZER_GOOGLE_CLIENT_ID=1234-abc.apps.googleusercontent.com
```

```sh
# 1. Data stack, provider keys (from .env or your shell), image push, worker stack.
export GROK_API_KEY="your-xai-api-key"
src/infra/scripts/deploy.sh

# 2. Studio + API function on Vercel, wired to the stacks (rotates its AWS key).
src/infra/scripts/deploy-frontend.sh
# Optional end-to-end check against the production domain:
LEGOLIZER_STUDIO_URL=https://legolizer.vercel.app src/infra/scripts/deploy-frontend.sh --smoke
```

`LEGOLIZER_IDLE_MINUTES` changes the idle timeout for `deploy.sh`. After this
first deploy, pushes to `main` redeploy the backend through
`.github/workflows/deploy.yml` once its one-time setup is done. See
[src/infra/README.md](src/infra/README.md) for the architecture, costs,
continuous deployment, and troubleshooting.

To delete every AWS resource, including saved builds:

```sh
src/infra/scripts/destroy.sh
```
