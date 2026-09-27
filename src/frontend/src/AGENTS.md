# AGENTS.md — `src/frontend/src/`

Application source for Legolizer Studio.

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../../AGENTS.md](../../../AGENTS.md)

## Files

| File | Role |
| --- | --- |
| `main.jsx` | `createRoot` + `StrictMode`; imports the font weights in use (Young Serif 400, Atkinson Hyperlegible 400/700, Courier Prime 400/700) and `styles.css` |
| `App.jsx` | Shell: decorative `.backdrop` bush layers, stud brand mark, header nav (`#new-build`, `#library` anchors), session (sign in / out), generation-pause banner and admin toggle, selected build (`?build=` share links, localStorage), viewer chrome, build panel (rename, primary actions, publish / copy-link, view options), parts dialog, AR entry, assembly trigger key, click/region select tools for refine |
| `AccountMenu.jsx` | Google Identity Services loader and `GoogleButton`, signed-in account chip (avatar, name, `sign out` text button) |
| `BuildLibrary.jsx` | Page body in order: create panel (`#new-build`; text/image form with upload/gallery + camera capture, or a signed-out card pointing at the header button), job rows, the `workspace` slot App passes in, then the library (`#library`; my sets / gallery tabs over a wrapping card grid); polling; opens a build when its job succeeds |
| `AssemblyIndicator.jsx` | Job-row loading detail: randomized isometric SVG brick sequences + rolling phrases |
| `Viewer.jsx` | Three.js scene, `LDrawLoader`, orbit/pan, grid/edges, brick click + two-anchor region select + highlight, assembly (brick-drop) animation + layer slider; pauses when AR is open |
| `ARMode.jsx` | WebXR immersive AR: session from AR click, then load/place; rotate/pan; fallback; flat dark overlay titled with the set name |
| `RefinePanel.jsx` | Reprompt form for `refineBuild` (selected bricks, or the whole model); labels use App's current `buildName` (after a rename) |
| `api.js` | `VITE_*` config, `fetch` helpers, `assetUrl`, demo stubs |
| `styles.css` | Tokens on `:root`, then sections (base, layout, header, forms, library, stage, panel, dialogs, AR, responsive) |

## Conventions

- Inherit root [AGENTS.md](../../../AGENTS.md): minimal comments (non-narrative;
  only when code is unclear); update this file in the same change when the
  file map or viewer/API conventions shift.
- UI copy is lowercase, written that way in the JSX (never `text-transform`), including
  aria-labels and titles; user content and server messages stay as sent.
- Brick theme: surfaces read as bricks, not cards. No outlined boxes: solid fill blocks
  with `--radius` corners and a hard offset "edge" (`box-shadow: 0 var(--press) 0 …`,
  no blur), 3px ink rules, or a 6px state bar. Stud strips (`::before` radial-gradient,
  `space no-repeat` so studs never clip) sit on the create panel, the stage (via
  `.workspace::before` in grid area 1/1/2/2, since `.stage` clips) and set thumbnails.
  Colors come from the red / yellow / blue / green tokens; the page is near-white
  `--paper` over the `.backdrop` bush layers (`--bush-1…5`, lighter to more saturated
  going down). Dialogs carry one 3px ink border. A disabled button must stay legible on
  its background (the build button goes translucent white, not grey).
- Keep API calls in `api.js`; components should not invent ad-hoc endpoints.
- Abort in-flight fetches when switching builds (`AbortSignal`).
- Preserve `Idempotency-Key` on POST retries after network errors.
- Viewer: dispose geometries/materials/renderer on unmount; cap
  `devicePixelRatio` at 2; load `assets.colors` then packed `assets.model`.
- Select / refine: `selectTool` is `click` (raycast toggle) or `region`
  (two bricks as opposite corners of a cell AABB; every visible piece that
  overlaps that box is selected). Selection payload stays `{ key, min, max }`.
- Default view (`reset`, on load and on `resetKey`): `frameBox` fits the model's
  bounds along the fixed home direction, inside `VIEW_INSETS` (top margin /
  toolbar + hint); never closer than the home distance. Update `VIEW_INSETS` if the
  stage overlays change size.
- The grid is always on (`settings.grid` stays `true`; there is no toggle).
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
- Layout and nav: App renders the workspace (viewer + build panel, or its loading /
  error state) into `BuildLibrary`'s `workspace` prop so the library sits below it
  while its state stays in `BuildLibrary`. Header links send `navRequest`
  (`{ target: 'new' | 'mine' | 'gallery', key }`): `new` scrolls to `#new-build` and
  focuses the prompt; the others switch the tab and scroll to `#library`. Picking a set
  card, or a job succeeding, scrolls the workspace into view (instant under
  `prefers-reduced-motion`). No router, no hash state.
- Size: the slider or **auto** (no `maxSize` sent; the server picks). There is no
  client-side size suggestion; `POST /sizing` stays on the server but the studio does not call it.
- Sign-in: the page shows exactly one Google button, the header's `AccountMenu`; the
  signed-out create card only points at it. Load the Google Identity Services script only when a signed-out visitor
  needs the button. It is initialized once per page, and `GoogleButton` routes the
  credential to the latest `onCredential`. Editing tools (Select / Region / refine)
  need `session.user` and a build whose `mine` is not `false`. A stored selection that
  answers 404 (another user's set, or signed out) falls back to `VITE_BUILD_ID`.
- Default selection (shared link, remembered set, `VITE_BUILD_ID`, else newest saved set,
  else newest gallery set). Little Bot (`demoBuildId`) is never the default outside demo
  mode, and a remembered `robot-corrected` is ignored.
- Library polling: while the library is open (signed in, or auth `off`), jobs poll every
  4 s. Saved sets load once, then again only when a job succeeds or `refreshKey` changes;
  do not reintroduce whole-list polling. The gallery loads on demand when shown (again
  after `refreshKey` changes), pages with **Load more**, and is never polled.
- Sharing: publishing changes only a visibility override in `App`, never `data.build`,
  because a new `build` object makes `Viewer` reload the model. `?build=<id>` opens that
  set on load; selecting another set (or a 404 fallback) clears the parameter.
- Rename (owners, allowed while generation is paused): `api.renameBuild` sets a name
  override in `App` (same rule as sharing, never `data.build`) and bumps `libraryKey`.

## Touch carefully

- Changing polling interval or render loop behavior is a performance change—
  call it out in the PR or file an issue if deferred.
- Image upload validation (type/size/dimensions) must stay aligned with
  `legolizer.uploads` and OpenAPI.

## Agent backlog

- #82 — Region (two-anchor) multi-brick selection for refine (filed 2026-09-26)
- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
