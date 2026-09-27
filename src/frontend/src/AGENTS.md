# AGENTS.md — `src/frontend/src/`

Application source for Legolizer Studio.

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../../AGENTS.md](../../../AGENTS.md)

## Files

| File | Role |
| --- | --- |
| `main.jsx` | `createRoot` + `StrictMode`; imports `styles.css` |
| `App.jsx` | Shell: selected build, viewer chrome, parts dialog, AR entry, localStorage, assembly trigger key, click/lasso select tools for refine |
| `BuildLibrary.jsx` | Text/image generation form (upload/gallery + camera capture), jobs UI, saved-set carousel, polling; opens a build when its job succeeds |
| `Viewer.jsx` | Three.js scene, `LDrawLoader`, orbit/pan, grid/edges, brick click + lasso multi-select + highlight, assembly (brick-drop) animation + layer slider; pauses when AR is open |
| `ARMode.jsx` | WebXR immersive AR: session from AR click, then load/place; rotate/pan; fallback |
| `RefinePanel.jsx` | Reprompt form for `refineBuild` (selected bricks, or the whole model) |
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
- Select / refine: `selectTool` is `click` (raycast toggle) or `lasso`
  (freehand path; pieces whose projected centers fall inside are added).
  Lasso disables orbit for the stroke and paints an SVG overlay; short
  taps still toggle one brick. Selection payload stays `{ key, min, max }`.
- Assembly + layer slider: layers are `LDrawLoader`'s `userData.buildingStep`
  (one `0 STEP` per layer from `legolizer.ldraw`). Auto-play runs only when a
  build is opened (`assembleKey` from `App.selectBuild`), never on reload, and
  is decided before the model is first added to the scene (no full-model flash).
  Sliding up drops the new layers; sliding down hides instantly. Play finishes
  from the current layer (replays from 0 at the top); pause holds the layer in
  the air. Slider and play/pause must never move the camera. `prefers-reduced-motion`: no auto-play or falling.
  Pieces always come to rest at their unmodified positions (picking relies on it).
- AR: start `requestSession` from the studio AR click (user activation); keep the
  DOM overlay root fixed on `document.body` (do not reparent it); load local
  packed MPD + `LDConfig.ldr` after the session is live; dispose the XR session
  and overlay on close so studio generate/orbit/parts keep working.
- Demo mode (`VITE_DEMO === 'true'`): static `/demo/*`, no generation UI,
  ignore selected-build localStorage.

## Touch carefully

- Changing polling interval or render loop behavior is a performance change—
  call it out in the PR or file an issue if deferred.
- Image upload validation (type/size/dimensions) must stay aligned with
  `legolizer.uploads` and OpenAPI.

## Agent backlog

- #82 — Lasso multi-brick selection for refine (filed 2026-09-26)
- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
