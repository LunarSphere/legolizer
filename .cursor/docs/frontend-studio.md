# Frontend Studio

## Summary
React + Vite + Three.js SPA for prompting builds, viewing packed models,
browsing the library/gallery, refining selections, and optional AR. All HTTP
goes through `api.js` to same-origin `/api/v1`. Text builds support Auto or an
explicit 16–32 stud target size.

## Key modules / paths
- `src/frontend/src/App.jsx` — shell and generation flow
- `src/frontend/src/api.js` — API client / asset URLs (no secrets in `VITE_*`)
- `src/frontend/src/Viewer.jsx` — WebGL packed MPD viewer
- `src/frontend/src/BuildLibrary.jsx` — saved/demo/gallery browsing, size slider
- `src/frontend/src/RefinePanel.jsx` — generative refine UI
- `src/frontend/src/AccountMenu.jsx` — sign-in chrome
- `src/frontend/src/ARMode.jsx` — mobile AR mode
- `src/frontend/src/styles.css` — single stylesheet / tokens
- `src/frontend/public/privacy.html` — OAuth consent privacy policy page

## Invariants
- Small surface: no router / global state library beyond React hooks
- Packed MPD + `LDConfig.ldr` required for WebGL; no remote parts library
- Production is same-origin API via Vercel rewrite

## Last updated
2026-09-27
