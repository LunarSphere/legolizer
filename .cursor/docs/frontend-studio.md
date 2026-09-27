# Frontend Studio

## Summary
React + Vite + Three.js SPA for prompting builds, viewing packed models,
browsing the library/gallery, refining selections, and optional AR. All HTTP
goes through `api.js` to same-origin `/api/v1`. Builds use auto (the server picks)
or an explicit 16–32 stud target size; the studio has no size-suggestion button.
Page order: create panel, job rows, workspace (viewer + build panel), library.

## Key modules / paths
- `src/frontend/src/App.jsx` — shell (header nav, account, pause banner), build panel
  (owner rename, instructions / parts / download, sharing, view options; the grid is
  always on), parts dialog
- `src/frontend/src/api.js` — API client / asset URLs (no secrets in `VITE_*`)
- `src/frontend/src/Viewer.jsx` — WebGL packed MPD viewer
- `src/frontend/src/BuildLibrary.jsx` — create panel (text / photo, size slider, detail
  toggle), job rows, workspace slot, my sets / gallery card grid; header nav requests
  switch tabs and scroll; signed-out visitors get one sign-in button (the header's)
- `src/frontend/src/RefinePanel.jsx` — generative refine UI
- `src/frontend/src/AccountMenu.jsx` — sign-in chrome
- `src/frontend/src/ARMode.jsx` — mobile AR mode
- `src/frontend/src/styles.css` — single stylesheet; workshop tokens (paper, fill,
  sheet, ink, one signal accent) on `:root`; no outlined boxes, radius 0, 14px minimum
  text; self-hosted Young Serif (headings), Atkinson Hyperlegible (UI), Courier Prime
  (numbers). UI copy is lowercase, written that way in the JSX
- `src/frontend/public/privacy.html` — exists only to satisfy Google's OAuth consent-screen privacy-policy URL requirement (needed to enable Google auth); not linked from Studio

## Invariants
- Small surface: no router / global state library beyond React hooks
- Packed MPD + `LDConfig.ldr` required for WebGL; no remote parts library
- Production is same-origin API via Vercel rewrite

## Last updated
2026-09-27
