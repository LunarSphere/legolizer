# AGENTS.md — `tests/fixtures/`

Saved shape programs for offline generation regressions. Parent: [../AGENTS.md](../AGENTS.md).

- `garden-gate.json` snapshots the specialty example; the other initial fixtures
  snapshot local seaside market, Burj Khalifa, and Hagia Sophia generations.
- `hagia-sophia-original.json` intentionally has a floating arch. Its generated
  support repair must connect the build without changing the dome's cells.
- `hagia-sophia-repaired.json` contains the accepted endpoint support columns.
- `lighthouse-boundary-gap.json` preserves a failed live design with adjoining
  decimal-height courses. Tolerant half-open voxel faces must keep them connected.
- `treehouse-unsupported-rails.json` keeps the original failing treehouse: slab
  retiling must bond its base, while two genuinely floating rails stay rejected.
- `colosseum-floating-arches.json` preserves a failed generated build. Final
  pruning must remove exactly its two disconnected arches and preserve the rest.
- `trial-*.json` snapshots successful live prompt trials and is automatically
  included in the connected-build corpus. Store failures with a different prefix
  and add a focused regression with their expected repair or rejection.
- Fixtures contain shape programs only: no credentials, images, or generated
  meshes. Expected outcomes belong in `test_generation_regressions.py`.
- Retain failing inputs when adding a fix; do not replace them with hand-fixed
  programs. Run from repo root with unittest discovery as described in the parent.
