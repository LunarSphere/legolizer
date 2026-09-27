---
name: review-new-changes
description: >-
  Summarize new local or branch changes and how they differ from main without
  committing or pushing. Use when the user asks to review new changes, summarize
  the diff vs main, what changed on this branch, or a read-only change overview.
---

# Review new changes (read-only)

Summarize what differs from `main`. Do **not** commit, push, amend, stash in a
way that drops work, or open/merge a PR under this skill.

## Hard rule — observe only

**Forbidden:** `git commit`, `git push`, `git add` (unless needed only to
inspect—prefer unstaged review), force operations, deploy, or applying fixes.

**Allowed:** `git status`, `git diff`, `git log`, `git fetch` (read remote tips),
reading files for context, writing a run log under `.cursor/logs/` (required).

## Scope

Default comparison: **current branch / working tree vs `origin/main`** (fetch
first if stale).

Include:

1. Uncommitted changes (staged + unstaged + untracked), and
2. Commits on this branch not in `main` (`origin/main..HEAD`)

If the user names paths or a PR, narrow to that.

## Commands

```sh
git fetch origin main
git status -sb
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git diff origin/main...HEAD
git diff HEAD
git diff --cached
git status --porcelain
```

Untracked files will not appear in `git diff`; list them from `status` and skim
important ones if they matter to the summary.

## How to summarize

Be concise. Prefer path-level grouping over line-by-line dumps.

Cover:

- **Base** — tip of `origin/main` vs current `HEAD` / dirty state
- **Commits** — one line each (`origin/main..HEAD`), or `none`
- **Working tree** — dirty? yes/no; key unstaged/untracked paths
- **By area** — e.g. `.cursor/`, `src/legolizer/`, frontend, tests, infra
- **Behavioral impact** — user/API-visible vs docs/skills-only
- **Risks** — contract drift, missing tests, secrets, deploy touchpoints

Do not rewrite the change set. Do not start implementing follow-ups here.

## Persist log

Every run **must** write a log file and still reply in chat.

1. Ensure `.cursor/logs/` exists.
2. Write `.cursor/logs/review-new-changes-<YYYYMMDD-HHMMSS>Z.md` (UTC).
3. File contents: header (skill name, UTC ISO time, branch, `HEAD` short SHA,
   dirty yes/no) + the full output-format body. Optionally append `git diff
   --stat` / porcelain excerpts (no secrets).
4. End the chat reply with `Log: .cursor/logs/<filename>`.

See [../../logs/AGENTS.md](../../logs/AGENTS.md).

## Output format

```markdown
## Verdict
Clean / Has uncommitted work / Ahead of main / Diverged

## vs main
- Commits: …
- Files changed (committed): …
- Uncommitted: …

## Summary
<1–5 bullets of what changed and why it matters>

## Notable diffs
- `path`: <one-line what differed>

## Not committed or pushed
Confirmed: no commit/push performed.
```
