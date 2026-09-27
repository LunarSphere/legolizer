---
name: open-ticket
description: >-
  Open a GitHub issue for a new Legolizer feature, assign it to the invoking
  agent session (@me), create and switch to a ticket branch, then start
  implementation. Use when the user says open-ticket, open a ticket, file and
  build, or wants an issue plus implementation in one flow. Requires the user
  to specify which feature to ticket and develop—ask and stop if missing.
---

# Open ticket and implement

Create a GitHub issue, take assignment, branch for that ticket, then begin
implementation. Follow root `AGENTS.md` (PR on a feature branch; never merge;
tests for behavior changes).

## Hard gate — feature required

The user **must** name the feature (what to build) in the same message or a
clear follow-up.

If the feature is missing or too vague to file:

1. Ask once what feature to open an issue for and implement.
2. **Stop.** Do not create an issue, branch, or code until they answer.

Do not invent a feature from ambient chat context alone.

## Workflow

### 1. Normalize the request

From the user’s feature description, derive:

- **Title** — short imperative issue title
- **Slug** — lowercase kebab-case (≤40 chars), e.g. `region-multi-select`
- **Body** — goal, scope, non-goals, acceptance checks (enough for another agent)

### 2. Sync base branch

```sh
git fetch origin main
git checkout main
git pull origin main
```

If the working tree has unrelated dirty files, stop and ask how to proceed
(stash, commit elsewhere, or discard). Do not silently clobber work.

### 3. Create the GitHub issue and assign

Assign to the invoking session’s GitHub identity (`@me` = authenticated `gh`
user). Note agent ownership in the body (Cursor agents are not separate GitHub
users).

```sh
gh issue create --title "<title>" --assignee "@me" --body "$(cat <<'EOF'
## Goal
<user-visible outcome>

## Scope
- …

## Non-goals
- …

## Acceptance
- [ ] …

## Agent
Invoking Cursor agent owns implementation on the ticket branch.
Attribution allowed on commits/PR per root AGENTS.md.

EOF
)"
```

Capture the issue **number** from the URL/`gh` output. If `--assignee @me`
fails (permissions), create without assignee, report that, and continue—the
agent still owns the work in-session.

Optional: `gh issue edit <n> --add-assignee "@me"` if create succeeded without
assign.

### 4. Create and switch to the ticket branch

```sh
git checkout -b feat/<n>-<slug>
```

Example: issue 105 + `region-multi-select` → `feat/105-region-multi-select`.

Confirm `git branch --show-current` before editing code.

### 5. Begin implementation

1. Read nearest `AGENTS.md` files for touch points.
2. Implement the scoped feature only (no piggyback unrelated fixes—file separate
   issues for those).
3. Add/update tests when runtime behavior changes; keep OpenAPI / AGENTS in sync
   when those surfaces change.
4. Prefer a short plan in chat or `.cursor/plans/<slug>.md` only if the work is
   large; do not block on a full plan doc unless the user asks.

### 6. Finish the ticket session

When the feature work for this issue is done (same session unless the user
pauses):

1. Commit if the user asked (or when they ask to open a PR—then commit as part
   of that flow).
2. Push and open a PR with `.github/PULL_REQUEST_TEMPLATE.md` sections filled.
3. Reference the issue (`Fixes #<n>` or `Closes #<n>` when appropriate).
4. Do **not** merge the PR.

## Output (after issue + branch, before or as work starts)

```markdown
## Ticket
#<n> — <title> — <url>

## Branch
`<branch>`

## Assignee
@me (invoking gh user) / agent owns implementation

## Next
Starting implementation: <one-line focus>
```

## Forbidden

- Opening a ticket without a user-specified feature
- Committing directly to `main`
- Merging the PR
- Deploying or mutating AWS/Vercel under this skill
- Expanding scope beyond the filed issue
