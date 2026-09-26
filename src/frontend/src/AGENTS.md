# AGENTS.md — `src/frontend/src/`

Application source for Legolizer Studio.

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../../AGENTS.md](../../../AGENTS.md)

## Files

| File | Role |
| --- | --- |
| `main.jsx` | `createRoot` + `StrictMode`; imports `styles.css` |
| `App.jsx` | Shell: selected build, viewer chrome, parts dialog, localStorage |
| `BuildLibrary.jsx` | Text/image generation form, jobs UI, saved-set carousel, polling |
| `Viewer.jsx` | Three.js scene, `LDrawLoader`, orbit/pan, grid/edges, brick picking + selection highlight |
| `RefinePanel.jsx` | Reprompt form for `refineBuild` (selected bricks, or the whole model) |
| `api.js` | `VITE_*` config, `fetch` helpers, `assetUrl`, demo stubs |
| `styles.css` | Global layout and tokens |

## Conventions

- Keep API calls in `api.js`; components should not invent ad-hoc endpoints.
- Abort in-flight fetches when switching builds (`AbortSignal`).
- Preserve `Idempotency-Key` on POST retries after network errors.
- Viewer: dispose geometries/materials/renderer on unmount; cap
  `devicePixelRatio` at 2; load `assets.colors` then packed `assets.model`.
- Demo mode (`VITE_DEMO === 'true'`): static `/demo/*`, no generation UI,
  ignore selected-build localStorage.

## Touch carefully

- Changing polling interval or render loop behavior is a performance change—
  call it out in the PR or file an issue if deferred.
- Image upload validation (type/size/dimensions) must stay aligned with
  `legolizer.uploads` and OpenAPI.

## Agent backlog

_(none yet)_
