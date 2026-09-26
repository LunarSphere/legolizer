# AGENTS.md — `src/frontend/src/`

Application source for Legolizer Studio.

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../../AGENTS.md](../../../AGENTS.md)

## Files

| File | Role |
| --- | --- |
| `main.jsx` | `createRoot` + `StrictMode`; imports `styles.css` |
| `App.jsx` | Shell: selected build, viewer chrome, parts dialog, AR entry, localStorage |
| `BuildLibrary.jsx` | Text/image generation form (upload/gallery + camera capture), jobs UI, saved-set carousel, polling |
| `Viewer.jsx` | Three.js scene, `LDrawLoader`, orbit/pan, grid/edges; pauses when AR is open |
| `ARMode.jsx` | WebXR immersive AR: hit-test place, rotate/tilt/pan, unsupported fallback |
| `api.js` | `VITE_*` config, `fetch` helpers, `assetUrl`, demo stubs |
| `styles.css` | Global layout and tokens |

## Conventions

- Inherit root [AGENTS.md](../../../AGENTS.md): minimal comments (non-narrative;
  only when code is unclear); update this file in the same change when the
  file map or viewer/API conventions shift.
- Keep API calls in `api.js`; components should not invent ad-hoc endpoints.
- Abort in-flight fetches when switching builds (`AbortSignal`).
- Preserve `Idempotency-Key` on POST retries after network errors.
- Viewer: dispose geometries/materials/renderer on unmount; cap
  `devicePixelRatio` at 2; load `assets.colors` then packed `assets.model`.
- AR: use local packed MPD + `LDConfig.ldr` only; dispose the XR session and
  renderer on close so studio generate/orbit/parts keep working.
- Demo mode (`VITE_DEMO === 'true'`): static `/demo/*`, no generation UI,
  ignore selected-build localStorage.

## Touch carefully

- Changing polling interval or render loop behavior is a performance change—
  call it out in the PR or file an issue if deferred.
- Image upload validation (type/size/dimensions) must stay aligned with
  `legolizer.uploads` and OpenAPI.

## Agent backlog

- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
