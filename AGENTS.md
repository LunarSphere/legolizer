# AGENTS.md — Legolizer

Guidance for coding agents working in this repository. Read this file before
changing code. When you enter a subdirectory, also read that directory's
`AGENTS.md` (and keep reading nested ones as you go deeper).

## What this project is

**Legolizer** turns a short object description (or a reference image) into a
voxelized LEGO-style model: an official-parts LDraw MPD, a parts list, optional
PNG render, and LPub3D PDF instructions. The geometry pipeline is Python; the
studio UI is a React + Vite + Three.js SPA.

Human docs: [README.md](README.md) (pipeline and CLI), [instructions.md](instructions.md)
(install/renderers), [src/frontend/README.md](src/frontend/README.md) (studio UI).

## Repository map

| Path | Role | Nested guide |
| --- | --- | --- |
| [`src/legolizer/`](src/legolizer/AGENTS.md) | Python package: design, voxelize, pack, export, render, HTTP API | yes |
| [`src/frontend/`](src/frontend/AGENTS.md) | Legolizer Studio (React / Three.js) | yes |
| [`tests/`](tests/AGENTS.md) | `unittest` regression suite for geometry/export | yes |
| [`src/`](src/AGENTS.md) | Source root (two products side by side) | yes |
| [`.github/`](.github/AGENTS.md) | CI, Dependabot, PR template | yes |

There is no monorepo tooling beyond `uv` (Python) and `npm` (frontend). Runtime
build artifacts live under `builds/` (gitignored). GitHub Actions runs Ruff,
unittest, and frontend lint/build on every PR (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Agent guides are shared

`AGENTS.md` files are part of this repository. They are not optional scratchpads.

**Same-change sync:** If a change alters agent-relevant layout, conventions,
tooling, module responsibilities, performance notes, or constraints, update the
affected `AGENTS.md` file(s) in the **same commit / PR**. Adding a lasting
source or test directory requires a new nested guide and a link from the parent.

`TASKS.md` stays local. Do not commit or push it. Prefer listing it in
`.git/info/exclude` rather than the shared `.gitignore`.

Human docs (`README.md`, `instructions.md`, `src/frontend/README.md`) stay the
place for install and product explanation. Keep `AGENTS.md` short and
navigational: what lives here, what not to break, where to go next. Put deep
explanations in README or focused code docs—not duplicated essays in every
guide, and not as narrative inline comments.

## Governing rules (all agents)

These override convenience. Do not weaken them for speed or “small” fixes.

### 1. Agent attribution is allowed

Commits, pull requests, and issues may include agent attribution. `Co-authored-by:`
trailers for Cursor, Copilot, Claude, ChatGPT, or another agent that did the
work are fine, including Cursor's commit and PR attribution settings.

The operator's git identity stays the author. Do not invent a human coauthor.

### 2. Every change goes through a PR on a new branch

- Do **not** commit directly to the default branch (`main` / `master`).
- Create a focused branch (e.g. `fix/…`, `feat/…`, `docs/…`), push, and open a
  pull request with `gh pr create` (or the equivalent).
- Keep PRs reviewable: one concern per branch when practical.
- Do not force-push the default branch. Do not skip hooks unless the human
  explicitly asks.
- **Finish with a PR.** When an agent completes work on an assigned issue or
  ticket, open the pull request in the same session—do not stop at a local
  commit or a pushed branch with no PR. Open the PR only after there is a real
  change set (not an empty placeholder on assignment).
- **PR body style.** Every PR must use the sections in
  [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md):
  Summary, Details, Decisions, Potential issues + justifications, Follow-ups,
  Performance, Test plan, and Agent checklist. Fill each section; write `none`
  or `none expected` when a section does not apply. Do not omit headings.
- **Never merge.** Agents must not merge pull requests, must not land commits on
  the default branch, and must not approve-and-merge their own PRs. Humans merge
  after review (CI green when Actions are enabled).

### 3. Stay on task; file issues for everything else

If you discover a bug, smell, missing test, or improvement that is **unrelated
to the current task**:

1. Do **not** fix it in the same change set.
2. Open a GitHub issue (`gh issue create`) with enough context for another agent
   to pick it up (repro, path, expected vs actual, suggested approach). Agent
   attribution on the issue is allowed.
3. Add a short note under **Agent backlog** in the nearest relevant `AGENTS.md`
   (link the issue). Update that note when the issue is closed.

Same rule for **performance**: speed and UX are first-class product goals. If
you spot an optimization opportunity (CPU, I/O, polling, WebGL, API latency),
file a GitHub issue and note it in the relevant `AGENTS.md`—do not piggyback
unrelated perf work onto the current PR unless the task explicitly asks for it.

### 4. Performance mindset

- Prefer changes that keep generation, viewer interaction, and library browsing
  snappy.
- Avoid unbounded work on the main thread (frontend) or serializing the single
  server worker further without cause.
- Measure or reason briefly in the PR when a change might affect latency or
  memory; file follow-up issues when you choose not to optimize now.

### 5. Minimal comments

Prefer clear names and structure over commentary. Comments are sparse and
non-narrative.

- Do **not** restate what the next lines do, narrate the change, leave
  changelog-style notes, or write essay walkthroughs in source.
- Comment only when the code is **not clear by itself**: non-obvious invariants,
  subtle constraints, surprising trade-offs, or external protocol quirks.
- Prefer deleting dead or commented-out code over keeping it “for later.”
- Short module/file purpose notes are fine when they orient a reader; do not
  decorate every function with a docstring that repeats the signature.
- Nested `AGENTS.md` files inherit this rule; do not weaken it locally.

## How to work here

### Tooling

| Area | Commands |
| --- | --- |
| Python deps | `uv sync` (add `--group dev` for Ruff) |
| CLI | `uv run legolizer …` |
| API server | `uv run python -m legolizer.server` |
| Lint / format (Python) | `uv run ruff check .` · `uv run ruff format .` |
| Tests | `uv run python -m unittest discover -s tests -v` |
| Frontend | `cd src/frontend && npm ci && npm run dev -- --port 5173 --strictPort` |
| Frontend lint / build | `cd src/frontend && npm run lint` · `npm run build` |
| Match CI locally | Python: `uv sync --group dev` then ruff check/format `--check` + unittest; frontend: `npm ci && npm run lint && npm run build` |

Secrets: copy `.env.example` → `.env` (never commit `.env`). Frontend: copy
`src/frontend/.env.example` → `.env.local` (gitignored). Never put provider keys
in `VITE_*` variables.

### Coding norms

- Match existing style in the file you edit (flat Python modules; small React
  surface; one global CSS file).
- Prefer extending existing modules over new layers of abstraction.
- Do not invent part geometry: only official LDraw parts from the whitelist in
  `src/legolizer/catalog.py`.
- Keep the OpenAPI contract in `src/frontend/api/openapi.json` aligned when
  changing the HTTP API surface.
- Follow **Minimal comments** (governing rule 5).

### Maintaining this doc system

- Every directory that holds project source or tests should have an `AGENTS.md`.
- When you add a new subdirectory of lasting code, add an `AGENTS.md` there and
  link it from the parent.
- When behavior or layout agents rely on changes, update the nearest guide in
  the **same** change set (see **Same-change sync** above).
- Keep guides short and navigational. Prefer linking to parent/root rules over
  restating them. Nested guides may point at root comment and sync rules in one
  line rather than copying the full text.
- **Agent backlog** sections are living scratchpads for filed issues—keep them
  accurate.

## Agent backlog

_Issues filed by agents for follow-up (add newest at top)._

<!-- Example:
- #N — short title (filed YYYY-MM-DD) — see src/legolizer/AGENTS.md
-->

- #22 — Require CI status checks on main (filed 2026-09-26) — see .github/AGENTS.md
- #16 — Refresh AGENTS.md guides: minimal comments, sync-on-change (filed 2026-09-26)
- #12 — Assembly video (filed 2026-09-26) — see src/frontend/AGENTS.md
- #11 — Dynamically selected grid size (filed 2026-09-26) — see src/legolizer/AGENTS.md
- #10 — legolizer.tech domain (filed 2026-09-26)
- #9 — AWS backend (filed 2026-09-26) — see src/legolizer/AGENTS.md
- #8 — Vercel hosting (filed 2026-09-26) — see src/frontend/AGENTS.md
- #7 — Published model gallery (filed 2026-09-26) — see src/frontend/AGENTS.md
- #6 — User accounts with saved models (filed 2026-09-26) — see src/legolizer/AGENTS.md
- #5 — Reprompt / generative infill on a region (filed 2026-09-26) — see src/legolizer/AGENTS.md
- #4 — Quality assurance (iterative) (filed 2026-09-26)
- #3 — Augmented reality mode (mobile) (filed 2026-09-26) — see src/frontend/AGENTS.md
- #2 — Support more LEGO bricks (filed 2026-09-26) — see src/legolizer/AGENTS.md
