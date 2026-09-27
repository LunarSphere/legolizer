# AGENTS.md — `.cursor/knowledge/`

Per-file knowledge base that mirrors lasting source paths. Parent:
[../AGENTS.md](../AGENTS.md). Root: [../../AGENTS.md](../../AGENTS.md).

## Mapping

| Source path | Knowledge path |
| --- | --- |
| `src/legolizer/foo.py` | `src/legolizer/foo.md` |
| `src/frontend/src/App.jsx` | `src/frontend/src/App.md` |
| `api/index.py` | `api/index.md` |
| `tests/test_foo.py` | `tests/test_foo.md` |

Replace the source extension with `.md`. Keep the same directory tree under
`.cursor/knowledge/`.

## What belongs here

- Short explanation of what the **corresponding file** does (role, key
  responsibilities, related paths)
- Update in the **same change** when that source file’s behavior or
  responsibility shifts (root AGENTS knowledge-base rule)

## What does not

- Generated trees: `builds/`, `node_modules/`, `.venv/`, `dist/`, lockfile churn
- Secrets or env values
- Long tutorials (link README / nested `AGENTS.md` instead)
- Replacing navigational `AGENTS.md` guides—those stay; this is per-file

## Doc shape

```markdown
# `relative/source/path`

## Role
One or two sentences.

## Key responsibilities
- …

## Related
- `path` — why

## Last updated
YYYY-MM-DD (issue or PR ref optional)
```

## Agent backlog

- #116 — Add codebase knowledge base and explore-knowledge skill
