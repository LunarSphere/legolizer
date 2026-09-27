---
name: debug
description: >-
  Debug Legolizer by evaluating code for correctness, reproducing failures,
  and fixing bugs in the Python pipeline, HTTP API, Studio UI, or local
  compose. Use when the user reports a bug, asks to debug, investigate a
  failure, or fix unexpected behavior. Always apply fixes when bugs are
  confirmed and report every change made.
---

# Debug Legolizer

Evaluate correctness, reproduce the failure, fix confirmed bugs, then report
every change. Do not stop at diagnosis when a safe fix is clear.

## Mandate

1. **Evaluate** the relevant code for correctness (logic, edge cases, contracts).
2. **Reproduce** before large edits when a failure was reported.
3. **Fix** bugs you confirm in-scope for the user’s request.
4. **Report all changes** every time—even when the list is empty (`none`).

Do not piggyback unrelated refactors. File out-of-scope smells as GitHub issues.

## Triage (pick one layer)

| Symptom | Likely layer | Start here |
| --- | --- | --- |
| CLI / design / voxel / pack / export wrong | Python geometry | `uv run legolizer …`, `tests/` |
| `/api/v1` 4xx/5xx, job stuck, asset 404 | `legolizer.server` + storage | server logs, job JSON under `builds/` |
| Studio blank / WebGL / parts list / PDF link | Frontend | browser console, `src/frontend/src/` |
| Works locally, fails on cloud | AWS worker or Vercel API | logs + `check-github-actions` for CD/CI |

Read the nearest `AGENTS.md` before changing that tree.

## Workflow

1. **Capture the failure**
   - Exact command or UI steps, expected vs actual, job id if any
   - Recent terminal output and (for UI) console / network errors
2. **Reproduce the smallest case**
   - Prefer CLI or a focused unittest over a full Studio round-trip
   - For jobs: inspect `builds/studio/jobs/<id>.json` and model dir artifacts
3. **Evaluate correctness** at the failing boundary
   - Read the code path that produces the symptom
   - Check invariants, null/empty handling, API/OpenAPI contract, and tests
   - Frontend only talks through `src/frontend/src/api.js` → `/api/v1`
   - Local Vite proxies to `127.0.0.1:8000`; production uses `api/index.py`
   - Heavy work (providers, render) runs in the worker/container, not Vercel
4. **Fix confirmed bugs**
   - Minimal change that restores correct behavior
   - Re-run the same repro (and targeted tests) after each fix
   - Add or extend a test when runtime behavior changes (root AGENTS rule 6)
5. **Report** using the output format below (required)

## Local commands

```sh
# API
uv run python -m legolizer.server

# Studio
cd src/frontend && npm run dev -- --port 5173 --strictPort

# Targeted tests
uv run coverage run -m unittest discover -s tests -v -k <pattern>

# Lint (Python)
uv run ruff check .
```

## Common pitfalls

- Missing `.env` / `src/frontend/.env.local` (copy from `.env.example`)
- Provider keys absent → design/image steps fail; check `.env`, never commit secrets
- Frontend pointed at wrong API or `VITE_DEMO=true` hiding live backend
- Packed MPD / `LDConfig.ldr` missing → WebGL loader fails
- Unofficial part IDs (only whitelist in `src/legolizer/catalog.py`)
- Stale `builds/` artifacts mistaken for a new run

## Output format

Always include every section. Under **Changes made**, list each edited path with
a one-line what/why. If nothing was edited, write `none`.

```markdown
## Repro
## Correctness findings
## Root cause
## Changes made
- `path/to/file`: <what changed and why>
## Verification
## Follow-ups
```

**Changes made** is mandatory. Prefer an explicit bullet list over prose so
nothing is omitted. Keep other sections short.
