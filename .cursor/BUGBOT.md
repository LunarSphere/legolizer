# Bugbot — Legolizer

Review every pull request update for logic and implementation correctness, including the head commit that will merge. Then give a short evaluation of how the change fits Legolizer.

## Product

Legolizer turns a short object description, or a reference image, into a voxelized model built only from official LDraw parts. A finished build is a stepped LDraw MPD, a parts list, an optional PNG render, and LPub3D PDF instructions.

Python owns design, voxelize, pack, export, render, and the HTTP API (`src/legolizer/`). The studio is a React + Vite + Three.js SPA (`src/frontend/`). Deployment lives in `src/infra/` (Docker, AWS CDK) and `api/` (Vercel). The shape program is the only 3D source of truth. Concept images guide colors and proportions; they are never measured into geometry.

Generation, viewer interaction, and library browsing should stay snappy.

## Every review

Always leave one pull-request comment with these sections, even when you find no defects. Keep each section to 1–3 bullets:

1. **Correctness** — defects, or none.
2. **Fit with Legolizer** — whether the change advances the product above, is neutral support for it, or works against it.
3. **Helpfulness** — who benefits, and whether the change is a net improvement.
4. **Improvements** — concrete next steps that would make the change more useful, or none.

File inline comments for real defects. Do not open a defect only to carry this summary.

## Skills and references

- Read the root `AGENTS.md` and the nested `AGENTS.md` for every directory the diff touches; they hold the governing rules.
- When agent skills are available, apply the relevant ones: AWS CDK / containers / IAM for `src/infra/**` and `.github/workflows/deploy.yml`, React and Three.js practices for `src/frontend/**`. If a skill is unavailable, fall back to the `AGENTS.md` guides; never block a review on it.

## Correctness

Flag these when the diff introduces them:

- Logic, data-shape, or API contract bugs, including error paths that swallow a failed build.
- Runtime behavior changes with no matching test update under `tests/`, or changed `src/legolizer/` lines likely to fall below 75% diff coverage.
- HTTP changes in `src/legolizer/server.py` that are not reflected in `src/frontend/api/openapi.json` and `src/frontend/src/api.js`.
- Committed secrets, `.env` files, or provider keys. Any `VITE_*` value that holds a secret is a defect. AWS or provider keys stored as GitHub secrets instead of OIDC are a defect.
- Invented, scaled, or approximate LEGO geometry. New parts belong in `src/legolizer/catalog.py` only as real LDraw part codes with correct stud footprints.
- A change that commits `TASKS.md`. `AGENTS.md` files are shared and should be committed when they change.
- Agent-relevant layout, conventions, tooling, module map, or constraint changes without an update to the affected `AGENTS.md` in the same pull request.
- Unrelated fixes bundled into the change instead of filed as GitHub issues.
- A pull-request body missing any section from `.github/PULL_REQUEST_TEMPLATE.md`.
- Changes under `src/infra/`, `src/legolizer/`, `api/`, `vercel.json`, `pyproject.toml`, or `uv.lock` redeploy the backend through `deploy.yml` on merge; flag it when the PR body does not mention that under Potential issues or Performance.
- Code-comment defects against root `AGENTS.md` **Minimal comments**:
  - Narrative or redundant comments that restate what the next lines do.
  - Changelog-style or “what I changed” comments left in source.
  - Essay-length walkthroughs or commented-out dead code kept “for later.”
  - Missing a short comment only where new code encodes a non-obvious invariant, subtle constraint, surprising trade-off, or external protocol quirk.
  - Do **not** demand comments on obvious code. Absence of comments is not a defect by itself.

## Fit with Legolizer

Treat a change as working against the product when it:

- Drops official-parts output, the parts list, or the instruction/PDF path without a replacement.
- Derives geometry by measuring the concept image.
- Moves generation or packing onto the browser main thread, or further serializes the single API worker without a stated reason.
- Points the viewer at a remote parts library instead of the packed MPD and `LDConfig.ldr`.
- Adds a router, global store, or new framework to the studio when an existing component can hold the behavior.

When the change is aligned but thin, say what is missing under **Improvements**. Prefer the smallest next step that would make it more useful. Name unrelated performance ideas there too; do not demand them in the same pull request.

Style nits are not defects unless they hide a bug or break a rule above.
