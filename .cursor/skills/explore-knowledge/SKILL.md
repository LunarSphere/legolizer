---
name: explore-knowledge
description: >-
  Explore and summarize Legolizer's per-file knowledge base under
  .cursor/knowledge/. Use when the user asks about the knowledge base, to
  summarize what areas of the codebase do, or to survey KB coverage. Writes a
  run log under .cursor/logs/ like other review/check skills.
---

# Explore knowledge base

Read `.cursor/knowledge/` and summarize it for the user. This skill is
**read-oriented** for the KB: do not rewrite large swaths of docs unless the
user asks to fill gaps. Always persist a run log.

Convention: [../../knowledge/AGENTS.md](../../knowledge/AGENTS.md).

## Hard rule — logging required

Every run **must** write a log and still reply in chat.

1. Ensure `.cursor/logs/` exists.
2. Write `.cursor/logs/explore-knowledge-<YYYYMMDD-HHMMSS>Z.md` (UTC).
3. File contents: header (skill, UTC ISO time, branch, `HEAD` short SHA, scope) +
   the full output-format body below.
4. End the chat reply with `Log: .cursor/logs/<filename>`.

No secrets. Do not commit the log unless asked. See
[../../logs/AGENTS.md](../../logs/AGENTS.md).

## Scope

Default: whole knowledge tree. If the user names a path prefix (e.g.
`src/legolizer` or `auth`), narrow to matching KB docs.

## Workflow

1. List `.cursor/knowledge/**/*.md` (skip `AGENTS.md` in summaries of “files
   documented” or treat it separately as the convention guide).
2. Skim Role sections (and Key responsibilities when needed).
3. Optionally note **coverage gaps**: lasting source files under `src/`, `api/`,
   `tests/` with no matching `.cursor/knowledge/...md` (ignore generated dirs).
4. Summarize by area; keep it short.

Do not implement product features under this skill. Do not mutate GitHub Actions,
AWS, or Vercel.

## Output format

```markdown
## Overview
<1–3 sentences on what the KB currently covers>

## By area
### src/legolizer
- `file`: <role one-liner>
### src/frontend
- …
### api / tests / infra
- …

## Coverage gaps
- missing KB for `path` … or `none noted`

## Suggested next reads
- `path` — why
```
