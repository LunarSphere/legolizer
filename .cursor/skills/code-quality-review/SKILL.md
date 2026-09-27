---
name: code-quality-review
description: >-
  Review Legolizer code for correctness, maintainability, AGENTS.md compliance,
  tests, and performance. Use when the user asks for a code review, quality
  pass, PR review, or to check changes against project standards.
---

# Code quality review

Review against this repo's rules—not generic style essays. Prefer findings with
paths and concrete fixes.

## Scope

Default to **uncommitted changes** or the **current branch vs `main`**, unless
the user specifies files/PR.

```sh
git status -sb
git diff origin/main...HEAD
git log --oneline origin/main..HEAD
```

## Checklist

### Correctness

- [ ] Behavior matches intent; edge cases handled
- [ ] No invented LDraw parts (whitelist only: `src/legolizer/catalog.py`)
- [ ] OpenAPI / `src/frontend/api/openapi.json` still matches HTTP changes
- [ ] Frontend uses `src/frontend/src/api.js`; no secrets in `VITE_*`

### Project rules (root `AGENTS.md`)

- [ ] Minimal, non-narrative comments
- [ ] Unrelated bugs/ideas filed as issues—not mixed into this change
- [ ] Behavior changes include/extend `tests/`; aim for ≥75% diff-cover on
      changed `src/legolizer/*` lines
- [ ] Nested `AGENTS.md` updated if layout/conventions changed
- [ ] No direct commits to `main` (review assumes a feature branch + PR)

### Style and tooling

```sh
uv run ruff check .
uv run ruff format --check .
cd src/frontend && npm run lint && npm run build
```

For Python behavior PRs:

```sh
uv run coverage run -m unittest discover -s tests -v
uv run coverage xml
uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=75 --include=src/legolizer/*
```

### Performance / product

- [ ] No unbounded main-thread work (frontend) or needless serialization of the
      single worker
- [ ] Avoid perpetual polling / idle WebGL loops / unvirtualized thumbnail floods
      unless the task requires them—file issues for follow-ups

### Infra / deploy touchpoints

If the diff touches `src/infra/`, `api/`, `vercel.json`, or `container.env`:

- [ ] Cost invariants (no NAT/ALB/always-on without human decision)
- [ ] Parity: runtime settings in `container.env`, not AWS-only hacks
- [ ] Secrets stay out of image, CDK context, and `VITE_*`

## Severity labels

- **Critical** — wrong behavior, security/secret leak, broken deploy gate
- **Important** — missing tests, AGENTS sync, contract drift
- **Suggestion** — clarity, small refactors, optional hardening

## Persist log

Every run **must** write a log file and still reply in chat.

1. Ensure `.cursor/logs/` exists.
2. Write `.cursor/logs/code-quality-review-<YYYYMMDD-HHMMSS>Z.md` (UTC).
3. File contents: header (skill name, UTC ISO time, branch, `HEAD` short SHA,
   scope reviewed) + the full output-format body below.
4. End the chat reply with `Log: .cursor/logs/<filename>`.

No secrets. Do not commit the log unless the user asks. See
[../../logs/AGENTS.md](../../logs/AGENTS.md).

## Output format

```markdown
## Verdict
Approve / Approve with nits / Request changes

## Findings
### Critical
### Important
### Suggestions

## Test gaps
## AGENTS / docs sync
```

Do not rewrite the PR. Do not merge. Do not expand scope into unrelated fixes.
