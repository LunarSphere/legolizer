# AGENTS.md — `src/frontend/scripts/`

Maintenance scripts for the frontend (run with `uv` from the **repository
root**, not from this folder alone).

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../../AGENTS.md](../../../AGENTS.md)

## Scripts

| Script | Purpose |
| --- | --- |
| `prepare_demo.py` | Rebuild `../public/demo/` from a finished build via `legolizer.web_assets.package_build` |

Example:

```sh
uv run python src/frontend/scripts/prepare_demo.py \
  --build builds/robot-corrected \
  --library /absolute/path/to/ldraw
```

## Conventions

- Scripts may import `legolizer.*`; they are part of the Python project, not
  npm.
- After regenerating demo assets, skim license files and `build.json` paths
  before committing large binary diffs.
- If you add another script here, document it in this file and in
  `../README.md` when operators need it.

## Agent backlog

_(none yet)_
