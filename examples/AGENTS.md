# AGENTS.md — `examples/`

Offline shape programs. Parent: [../AGENTS.md](../AGENTS.md).

- `garden-gate.json` exercises all five specialty part types on a connected base.
- Run with `uv run legolizer build "garden gate" --program examples/garden-gate.json
  --out builds/garden-gate`. Specialty previews require the official library and
  LDView (or a configured renderer); no provider keys are needed.
- Primitive coordinates are stud units; explicit `pieces.z` is in plate levels.
- Keep generated images, MPDs and parts lists in gitignored `builds/`.
