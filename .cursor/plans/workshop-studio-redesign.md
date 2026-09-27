# Workshop Studio redesign

Restyle and re-lay-out Legolizer Studio so the main tasks are obvious and the
UI reads as deliberately designed. No behavior changes beyond the explicit
additions/removals listed under **Scope changes**.

## Problems today

- Core actions are small and scattered: the prompt form is one card among
  many, Gallery is a 14px tab, Download is a 10px link, instructions are
  duplicated in the sidebar and a footer card.
- Most text is 9–11px.
- AI-default tells (see below) throughout copy and styling.

## Tells to remove (research summary)

Sources: slopdar.com, sailop.com "21 signs", yasirnajeep.com "Anti-Vibecoded
UI", designcode.io "Avoid AI slop", 925studios.co, uxskill "What is AI slop".

- Tracked uppercase eyebrows over every heading ("FROM IMAGINATION TO ASSEMBLY").
- Weightless copy: "Make room for a little wonder", "pieces of possibility",
  "Small bricks. Big possibilities.", "Take it for a spin", "masterpiece",
  sentence triads ("Explore it. Build it. Make it yours."), em-dash flourishes.
- Decorative status pills and dots that report nothing ("Connected workspace",
  "LIVE 3D PREVIEW", "DEMO BUILD / 001", "Ready" badge), fake breadcrumbs.
- Default font pairings pulled from Google Fonts (DM Sans + Manrope), muted
  sage palette used without a reason.
- Radial/linear gradient surfaces, backdrop blur, soft layered shadows, cards
  that lift on hover, rotated logo tile.
- An icon on every button and label; identical rounded cards everywhere with
  mismatched radii.
- Tiny low-contrast helper text; hierarchy by color fade instead of size.
- Duplicate CTAs for the same action.

## Direction: workshop / maker

A tool on a workbench: warm paper, hairline rules, dense and utilitarian,
data set in mono. Decisions, not defaults.

### Tokens (put on `:root`, use everywhere)

| Token | Value | Use |
| --- | --- | --- |
| `--paper` | `#f2eee5` | Page background |
| `--sheet` | `#faf8f3` | Panels, inputs, dialogs |
| `--ink` | `#1d1b18` | Text, strong rules, primary button |
| `--ink-2` | `#55504a` | Secondary text (never lighter for body copy) |
| `--rule` | `#d6cfc1` | Hairlines |
| `--rule-strong` | `#9f978a` | Input borders, focused dividers |
| `--signal` | `#c2410c` | The one accent: primary generate action, focus ring, active tool |
| `--signal-ink` | `#fff8f0` | Text on signal |
| `--ok` / `--warn` / `--err` | `#3f6b3a` / `#8a5a00` / `#a3321f` | Real states only |

- Type: **IBM Plex Sans** (UI/body) and **IBM Plex Mono** (numbers, part IDs,
  stud sizes, counts, short labels), self-hosted via `@fontsource/ibm-plex-sans`
  and `@fontsource/ibm-plex-mono` (drop the Google Fonts `@import`).
- Scale: 13 / 15 / 18 / 24 / 32px. Nothing below 13px. Body 15px, line-height 1.5.
  Weights 400 / 500 / 600 only.
- Labels: mono 13px, sentence case, no letter-spacing tricks.
- Radius: 2px on controls, 0 on panels and the stage. One radius, everywhere.
- Borders: 1px `--rule` hairlines separate regions; no drop shadows except a
  flat 1px `--ink` border on modal dialogs. No blur, no gradients, no hover lift.
- Buttons: primary = `--ink` fill (Generate uses `--signal`); secondary =
  `--sheet` with 1px `--rule-strong`; hover darkens/fills, never fades.
  Min height 40px; main actions 48px. Icons only where they carry meaning
  (viewer tools, download, external link).
- Focus: 2px `--signal` outline, 2px offset.
- Motion: keep existing functional motion (assembly drop, spinner, job
  indicator); add none decorative.

### Layout

1. **Header**: plain text wordmark "Legolizer"; nav links that scroll/jump
   to *New build*, *My sets*, *Gallery*; account on the right. No badges.
2. **New build** panel directly under the header, full width: a large prompt
   textarea with Text / Image as a clear two-way switch, then name, size, and
   detail options in one compact row, and a large Generate button. Job
   progress rows sit right under it.
3. **Workspace**: viewer stage (flat `--sheet`, hairline border) + right
   panel. Panel order: build name (with Rename for owners), description,
   the three primary actions as large equal buttons
   (*Instructions (PDF)*, *Parts list*, *Download .mpd*), stats in mono,
   palette, sharing, then view options. Remove the "From the screen to your
   shelf" card (duplicate).
4. **Library**: big section heading with *My sets* / *Gallery* as large
   tabs, cards in a wrapping grid (not a sideways scroller), mono metadata.
5. Footer: one line, factual ("Official LDraw parts. Not affiliated with the
   LEGO Group.").

### Copy rules

Plain, specific, verb-first. Say what a control does. No slogans, no
exclamation, no second-person hype. Keep every existing piece of real
information (limits, credit warnings, attribution, error text).

## Scope changes requested by the operator

- Rename a set (owner only): new `PATCH /api/v1/builds/{id}` with
  `{"name": "..."}` (1–80 chars trimmed); server, both stores, OpenAPI,
  `api.js`, UI in the build panel; tests in `test_server.py` / `test_storage.py`.
- Remove the **Suggest size** button (Auto remains; the server estimates).
- Remove the **Show grid** option (grid stays on).
- Signed-out page shows exactly one **Sign in with Google** button.

## Screenshots

Before shots are captured on `main` before any change; after shots per area.
They go on a `pr-screenshots/workshop-studio-redesign` branch and are linked
from the PR body.

## Tests

Only what changed: frontend `npm run lint` + `npm run build`,
`tests.test_frontend_encoding`, and `tests.test_server` / `tests.test_storage`
for the rename endpoint (with diff-cover on those lines).
