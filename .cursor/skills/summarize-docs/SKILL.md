---
name: summarize-docs
description: >-
  Summarize Legolizer area documentation under .cursor/docs/. Use when the user
  asks to summarize docs, overview documentation, or summarize a specific docs
  section (geometry, frontend, infra, etc.). Writes a run log under
  .cursor/logs/ like other review/check skills.
---

# Summarize docs

Read `.cursor/docs/` and summarize for the user. Default: **all** section docs.
If the user names a section (title, filename stem, or source region), summarize
**only** that section. Always persist a run log.

Convention: [../../docs/AGENTS.md](../../docs/AGENTS.md).

## Hard rule — logging required

Every run **must** write a log file and still reply in chat.

1. Ensure `.cursor/logs/` exists.
2. Write `.cursor/logs/summarize-docs-<YYYYMMDD-HHMMSS>Z.md` (UTC).
3. File contents: header (skill, UTC ISO time, branch, `HEAD` short SHA, scope:
   `all` or section id) + the full output-format body below.
4. End the chat reply with `Log: .cursor/logs/<filename>`.

No secrets. Do not commit the log unless asked. See
[../../logs/AGENTS.md](../../logs/AGENTS.md).

## Sections (map user wording → file)

| User may say | Doc |
| --- | --- |
| geometry, pack, export, ldraw | `geometry-and-export.md` |
| providers, CLI, concept, stylize | `providers-and-cli.md` |
| API, server, auth, storage, Vercel function | `api-and-storage.md` |
| frontend, Studio, UI, Three.js | `frontend-studio.md` |
| infra, deploy, CDK, AWS, CD | `infra-and-deploy.md` |
| tests, unittest, coverage | `tests.md` |

If ambiguous, ask once which section—or default to all.

## Workflow

1. Resolve scope: all section `*.md` (skip `AGENTS.md`) or one matched file.
2. Read Summary / Key modules / Invariants.
3. Write a concise summary (do not paste whole docs).
4. Persist log + reply.

Do not implement product features under this skill. Do not mutate Actions, AWS,
or Vercel. Do not rewrite docs unless the user asks to update a section.

## Output format

### All docs

```markdown
## Overview
<1–3 sentences>

## Sections
### <title>
<2–4 sentences or bullets>

## Suggested next reads
- `.cursor/docs/<file>.md` — why
```

### One section

```markdown
## Section
<title> (`<file>.md`)

## Summary
…

## Key modules
- …

## Invariants
- …
```
