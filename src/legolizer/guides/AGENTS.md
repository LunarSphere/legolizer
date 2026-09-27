# AGENTS.md — `src/legolizer/guides/`

Design guides, one per stylizer category. Parent: [../AGENTS.md](../AGENTS.md).

- One `<category>.json` per entry in `GUIDE_CATEGORIES` (`providers.py`):
  `advice` (short structural and color advice), `example` (the request it
  answers) and `program` (a small shape program).
- `design_guide` sends only the matching guide with the first design call, so
  keep each file small (roughly 10-15 parts, 16 studs or less).
- Advice must stay pose-neutral: a guide that dictates a pose ("stand on four
  legs") overrides the brief and produced floating limbs in testing.
- Every example must pack with no loose or disconnected pieces, exactly, using
  `DESIGN_COLORS` only; `test_generation_regressions.py` enforces this with an
  unlimited `time_budget` so the seeded restarts are deterministic (the dog,
  mug and cottage need restarts beyond attempt 0 with the current packer).
- Primitives only (no specialty `pieces`), so guides need no renderer.
