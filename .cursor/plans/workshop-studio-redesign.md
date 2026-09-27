# Workshop Studio redesign

> Superseded for colors, radius and shadows by the brick theme described in
> `src/frontend/src/AGENTS.md`; layout and copy decisions below still apply.

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
- Default font pairings (DM Sans + Manrope, Inter, and also the "safe
  designer" pairs like IBM Plex Sans + Plex Mono), muted sage palette.
- Everything in its own box: bordered cards, outlined panels, and 1px hairline
  rectangles around every group. Operator feedback on the first pass: "all
  these boxes with thin outlines" still read as AI-made.
- Radial/linear gradient surfaces, backdrop blur, soft layered shadows, cards
  that lift on hover, rotated logo tile.
- An icon on every button and label.
- Tiny low-contrast helper text; hierarchy by color fade instead of size.
- Duplicate CTAs for the same action.

## Direction: workshop / maker (v2, after operator review)

A tool on a workbench, not a dashboard. Paper, ink, and one warm accent.
Groups are made by **space, alignment, and type**, not by boxes.

### Surfaces and structure

- **No outlined cards.** Remove 1px borders around panels, cards, forms,
  the build panel, settings, size controls, share panel, set cards. A
  region is either open on the paper, or a **solid fill block** (no border)
  when it truly needs separation (the prompt area, the viewer stage).
- Separate sections with generous vertical space and, where a divider helps,
  one **2px `--ink` rule** spanning the column (like a ruled notebook), not
  hairline boxes. Keep hairlines only inside tables and under inputs.
- Inputs: no box; a 2px `--ink` underline on a slightly darker fill
  (`--fill`) reads as a form field on paper. Textarea may be a filled block.
- Set cards: the thumbnail on a `--fill` block with the name and metadata
  set underneath as plain text; selected = `--signal` underline/bar, not a
  ring.
- Modal dialogs: solid `--sheet`, a 2px `--ink` border is fine (one strong
  line, not a hairline card), no shadow.

### Tokens

| Token | Value | Use |
| --- | --- | --- |
| `--paper` | `#f1ece1` | Page background |
| `--fill` | `#e6dfd0` | Filled blocks: prompt area, inputs, thumbnails |
| `--sheet` | `#faf7f0` | Viewer stage, dialogs |
| `--ink` | `#1c1a17` | Text, rules, primary button |
| `--ink-2` | `#4f4a43` | Secondary text |
| `--signal` | `#c2410c` | The one accent: build button, active tab/tool, selection, focus |
| `--signal-ink` | `#fff8f0` | Text on signal |
| `--ok` / `--warn` / `--err` | `#3f6b3a` / `#8a5a00` / `#a3321f` | Real states only |

### Type

- **Young Serif** (`@fontsource/young-serif`) for the wordmark, headings,
  and the build name: chunky, warm, a little old-fashioned; not a trendy
  display face and never italic.
- **Atkinson Hyperlegible** (`@fontsource/atkinson-hyperlegible`, 400/700)
  for body and controls: made for legibility, uncommon in generated UIs.
- **Courier Prime** (`@fontsource/courier-prime`) only for numbers and codes:
  piece counts, part IDs, quantities, stud sizes, layer numbers. Like a
  label maker on the bench.
- Drop the IBM Plex packages.
- Scale: 14 / 16 / 20 / 28 / 40px. Nothing below 14px. Body 16px/1.5.
- **All lowercase UI copy**, written lowercase in the JSX (not
  `text-transform`), including the wordmark "legolizer", headings, buttons,
  labels, hints, errors written by us. Never uppercase, never letter-spaced.
  User content stays as typed (set names, descriptions, author names,
  attribution titles, server error messages, part IDs like `3001`, proper
  nouns in data). Acronyms in our copy go lowercase too (`pdf`, `ldraw`,
  `ar`), except file extensions shown as code (`.mpd`).
- Radius: 0 everywhere except round avatars. Buttons are flat rectangles.
- Buttons: primary = `--ink` fill; the build/generate button = `--signal`,
  large (56px). Secondary = `--fill` block, no border; hover darkens the
  fill. Text buttons are underlined ink. Icons only in the viewer toolbar
  and for download/external links.
- Focus: 2px `--signal` outline, 2px offset.
- Motion: keep existing functional motion; add none decorative.

### Layout

1. **Header**: wordmark "legolizer" in Young Serif; nav "new build",
   "my sets", "gallery" at 16px; account on the right. No badges. A 2px ink
   rule under the header.
2. **New build**: directly under the header, full width, on a `--fill`
   block: a big question heading, a large textarea, text / image switch,
   then name, size, and detail options in one row, and the big signal
   build button. Job progress rows right under it, as plain lines.
3. **Workspace**: viewer stage (`--sheet` block, no border) + right column
   open on the paper: build name (Young Serif 28px, rename for owners),
   description, the three primary actions as large equal buttons (*build
   instructions (pdf)*, *parts list*, *download (.mpd)*), counts in Courier
   Prime, colors, sharing, view options. No duplicate "next step" card.
4. **Library**: big heading with *my sets* / *gallery* as large tabs
   (active = signal underline), wrapping grid of set cards (no sideways
   scroller).
5. Footer: one plain line.

### Copy voice

Lowercase, conversational, a little wry; like a friend at the next workbench,
not a pitch deck. Full sentences, joined with semicolons where two thoughts
belong together. No slogans, no triads, no "unlock / elevate / seamless",
no exclamation marks, no rhetorical headlines on every block. Most lines are
just helpful. Keep every piece of real information (limits, credit warnings,
attribution, error details).

Examples of the voice (adapt, don't paste everywhere):

- create heading: "what are we building?" — hint: "describe it in a sentence
  or two, or hand over a photo; we'll work out the bricks."
- build button: "build it"; while sending: "sending it off…"
- detail toggle: "flesh out short prompts" — "a quick model adds color and
  detail before the design starts; you'll see what it wrote on the finished
  set."
- size auto hint: "left on auto, we'll pick a size that suits the thing."
- credits note: "takes a few minutes; it does spend api credits."
- stage hint: "drag to turn it; scroll to get closer."
- parts dialog: "parts list" — "55 pieces across 12 part-and-color
  combinations; the bricklink links open in a new tab."
- gallery empty: "nothing here yet; publish one of yours and be the first."
- sign-in: "sign in with google to start building; your sets will be waiting
  when you come back."
- footer: "made from official ldraw parts. lego is a trademark of the lego
  group, which has nothing to do with this site."

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
