# Strict Mode Rules

Apply these on top of the default rules in SKILL.md when strict mode is active.

## Author, non-negotiable

Every commit must be authored as:

```
name  = D1ZZY4
email = 176969112+D1ZZY4@users.noreply.github.com
```

Set before every commit session:
```bash
git config user.name "D1ZZY4"
git config user.email "176969112+D1ZZY4@users.noreply.github.com"
```

Verify with `git log -1 --format="%an <%ae>"` before pushing. A commit authored as "Replit
Agent", "replit-agent", or any other identity is rejected. Amend it immediately if it hasn't
been pushed yet.

If the user names a different project with a different required author or email, use that
instead. The pattern is the same, only the identity changes.

## Rules

- **English only.** Every part of the commit message (subject, body, comments), no exceptions.
- **Scope required.** Every subject line uses `type(scope): summary`. No bare `type: summary`.
- **Body required.** Every commit gets a Markdown body explaining the why, never subject-only.
- **No em dashes or en dashes.** Not in the subject, not in the body, not anywhere in the
  message, including inside literal shell commands or flags. Use a comma, colon, period, or
  parentheses instead.
- **No emoji.** Not in the subject, not in the body, ever.
- **One concern per commit.** Must be reversible without losing unrelated work. If you find
  yourself writing "and also," split it.
- **Never bundle unrelated files.** A single commit touching 15+ files across 5 different
  concerns is an AI anti-pattern. Split by concern.
- **Banned words: `phase`, `session`, `iteration`, `step`.** Plan-document words, not change
  descriptions.
- **No generic AI summaries** like "Update agent documentation while refreshing..." or
  "Address findings from audit." Write the actual change. A `Co-authored-by` trailer for an
  agentic tool is still fine here, see `message-style.md` for the format.
- **Derive the message from the real diff**, never from a checklist or plan document.
- **Verify before committing.** Run the project's typecheck, lint, and build commands before
  each commit. A failing build means the commit is incomplete.
- **Never amend or squash commits already pushed to origin/main** unless explicitly instructed.
  Rewriting public history breaks the branch for everyone.

## Example of a good commit

```
fix(rom-form-modal): validate URL scheme on download_link

Reject `javascript:` and `data:` URLs in the Zod schema for
`download_link` and `donate_link`.

Mirrors the existing validation on `RomCard` and `InfoTab`.
```

## Another good example, with a breaking change

```
feat(orders)!: rename checkout endpoint

BREAKING CHANGE: clients on `/v1/orders` must migrate to `/v1/checkout`
before 2026-06-01. The old route returns 410 after that date.

Consolidates the order flow into a single checkout resource so the
mobile client only has one endpoint to poll for status.
```

## Example of a bad commit (do not do this)

```
refactor: Phase 3, security fixes, bug fixes, and accessibility improvements

Security:
- Remove spam-protection note from FeedbackForm
- Add URL scheme guards for download_link/donate_link

Bug fixes:
- Wire filterPillVariants into BrandFilter
- Replace rounded-* with wobble.* in RomFormModal, FeedbackTab, RomGrid
...
```

17 unrelated changes in one commit, no scope, contains "Phase 3." Split into 8 to 17 focused
commits, each with its own scope and its own message describing one logical change.
