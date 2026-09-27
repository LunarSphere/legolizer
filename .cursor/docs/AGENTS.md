# AGENTS.md — `.cursor/docs/`

Area-level documentation for agents. Parent: [../AGENTS.md](../AGENTS.md).
Root: [../../AGENTS.md](../../AGENTS.md).

## Sections

| Doc | Covers source regions |
| --- | --- |
| [`geometry-and-export.md`](geometry-and-export.md) | `catalog`, `shape`, `model`, `solver`, `ldraw`, `preview`, `web_assets` |
| [`providers-and-cli.md`](providers-and-cli.md) | `providers`, `cli`, `reference`, `uploads`, `render`, `guides/` |
| [`api-and-storage.md`](api-and-storage.md) | `server`, `auth`, `storage`, `api/index.py` |
| [`frontend-studio.md`](frontend-studio.md) | `src/frontend/` Studio UI |
| [`infra-and-deploy.md`](infra-and-deploy.md) | `src/infra/`, `vercel.json`, CD workflows |
| [`tests.md`](tests.md) | `tests/` regression suite |

## What belongs here

- Short summaries of **broader regions** (what the area does, key modules,
  invariants)—not one doc per source file
- Update the **relevant section doc** in the **same** change when that region’s
  behavior or responsibilities shift (root AGENTS rule 7)

## What does not

- Per-file mirrors of every source path
- Generated trees, secrets, long product tutorials (link README / nested
  `AGENTS.md`)
- Replacing navigational `AGENTS.md`—those stay; these are area summaries

## Doc shape

```markdown
# <Area title>

## Summary
Short paragraph.

## Key modules / paths
- `path` — one line

## Invariants
- …

## Last updated
YYYY-MM-DD
```

## Agent backlog

- #116 — documentation + summarize-docs skill
