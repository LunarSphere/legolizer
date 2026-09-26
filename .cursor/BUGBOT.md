# Bugbot — Legolizer

Review every pull request for implementation correctness and for fit with the product. Run this on each update, including the head commit that will merge.

## Product

Legolizer turns a short object description, or a reference image, into a voxelized model built only from official LDraw parts. A finished build is a stepped LDraw MPD, a parts list, an optional PNG render, and LPub3D PDF instructions.

Python owns design, voxelize, pack, export, render, and the HTTP API (`src/legolizer/`). The studio is a React + Vite + Three.js SPA (`src/frontend/`). The shape program is the only 3D source of truth. Concept images guide colors and proportions; they are never measured into geometry.

Generation, viewer interaction, and library browsing should stay snappy.

## Every review

Always leave one pull-request comment with these sections, even when you find no defects:

1. **Correctness** — defects, or none.
2. **Goal alignment** — whether the change advances the product above, is neutral support for it, or works against it.
3. **Helpfulness** — who benefits, and whether the change is a net improvement.
4. **Improvements** — concrete next steps that would make the change more useful, or none.

File inline comments for real defects. Do not open a defect only to carry this summary.

## Correctness

Flag these when the diff introduces them:

- Logic, data-shape, or API contract bugs, including error paths that swallow a failed build.
- Geometry, packing, or export behavior changes with no matching update under `tests/`.
- HTTP changes in `src/legolizer/server.py` that are not reflected in `src/frontend/api/openapi.json` and `src/frontend/src/api.js`.
- Committed secrets, `.env` files, or provider keys. Any `VITE_*` value that holds a secret is a defect.
- Invented, scaled, or approximate LEGO geometry. New parts belong in `src/legolizer/catalog.py` only as real LDraw part codes with correct stud footprints.
- A change that commits `TASKS.md`. That file stays on the local working tree. `AGENTS.md` files are shared and should be committed when they change.

## Goal alignment

Treat a change as working against the product when it:

- Drops official-parts output, the parts list, or the instruction/PDF path without a replacement.
- Derives geometry by measuring the concept image.
- Moves generation or packing onto the browser main thread, or further serializes the single API worker without a stated reason.
- Points the viewer at a remote parts library instead of the packed MPD and `LDConfig.ldr`.
- Adds a router, global store, or new framework to the studio when an existing component can hold the behavior.

When the change is aligned but thin, say what is missing under **Improvements**. Prefer the smallest next step that would make it more useful. Name unrelated performance ideas there too; do not demand them in the same pull request.

Style nits are not defects unless they hide a bug or break a constraint above.
