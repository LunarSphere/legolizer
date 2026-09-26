## Summary

<!-- 1–3 sentences: what changed and why it matters. -->

## Details

<!-- Scope of the change: areas touched, behavior before vs after, and anything a reviewer should read carefully. -->

## Decisions

<!-- Non-obvious choices. Note alternatives considered and why this approach won. Write "none" if N/A. -->

## Potential issues + justifications

<!-- Known risks, limitations, sharp edges, or incomplete paths — and why shipping anyway is acceptable. Write "none" if N/A. -->

## Follow-ups

<!-- Deferred work, filed GitHub issues (with links), or "none". Do not bury unrelated fixes here; file issues instead. -->

## Performance

<!-- Latency, memory, polling, WebGL, or API impact — or "none expected". -->

## Test plan

- [ ] `uv sync --group dev && uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run coverage run -m unittest discover -s tests -v && uv run coverage xml && uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=75 --include=src/legolizer/*`
- [ ] `cd src/frontend && npm ci && npm run lint && npm run build`
- [ ] Manual / smoke steps relevant to this change (describe below if any)

## Agent checklist

- [ ] PR body fills every section above (use `none` / `none expected` when empty)
- [ ] Behavior changes include new/updated automated tests (root AGENTS rule 6); ≥75% coverage of changed `src/legolizer` lines (diff-cover)
- [ ] OpenAPI (`src/frontend/api/openapi.json`) and `src/frontend/src/api.js` updated if the HTTP API changed
- [ ] Affected `AGENTS.md` file(s) updated in this PR if layout, conventions, tooling, or constraints changed
- [ ] `TASKS.md` is not included in this PR
- [ ] Unrelated bugs or perf opportunities filed as GitHub issues (not fixed here)
- [ ] Did not merge; left for human review after CI
