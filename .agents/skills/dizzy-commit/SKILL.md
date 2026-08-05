---
name: dizzy-commit
description: >
  Enforce disciplined Conventional Commits and a clean working tree on every git commit.
  Use this skill proactively, not only when the user explicitly says "commit" or names the
  skill. Trigger it any time you finish a coding task and the working tree has uncommitted
  changes, any time the user says "commit", "git commit", "push", "stage", "/commit",
  "caveman commit", "strict commit", "dizzy-commit", or a clear synonym, and any time you are
  about to end a turn or session with dirty working tree state. Applies natively in any
  project, with a stricter mode available for projects that require a fixed commit author and
  extra banned-word rules.
---

# Dizzy Commit

Everything this skill needs is bundled here. No repo setup, no external rules file to check.
This file is the workflow index. Details live in `references/`, load the specific file for
the step you're on rather than guessing.

## Two modes

- **Default mode** (used automatically, always): the rules in `references/message-style.md`.
- **Strict mode**: triggered when the user says "strict commit", "strict mode", or explicitly
  asks to enforce a fixed commit author or banned-word rules for a repo. Read
  `references/strict-mode.md` for the extra constraints and apply them on top of default mode,
  not instead of it.

If unsure which mode applies, ask once, or default to the global rules. They're a safe
baseline either way.

## Step 0: Trigger proactively

Don't wait for the exact word "commit" or the skill name. Read `references/proactive-trigger.md`
for the full check-in flow (when to check in, the Yes/No/custom question, the follow-up about
whether context is needed). Short version: if you just finished coding and the tree is dirty,
check in before ending your turn; if the user already asked for a commit, skip straight to
Step 1.

## Step 1: Inspect the diff

```bash
git status --short
git diff            # unstaged
git diff --cached   # staged
```

Never write a commit message from memory or a plan/checklist. Always derive it from the
actual diff.

## Step 2: Group and stage safely

Read `references/staging-and-gitignore.md` for the full rules. Short version: group changed
files by logical concern (one commit per concern, split unrelated changes), and never stage
or commit a file covered by `.gitignore`, checking with `git check-ignore -v <file>` before
adding anything.

## Step 3: Write the message

Read `references/message-style.md` for the full format, subject and body rules, the commit
type table, and the list of things that never belong in a commit message (em dashes, emoji,
banned words, generic AI summaries). Scope is always mandatory, body is always mandatory and
always Markdown, and the body should read like a senior developer wrote it, not like an
enumerated file-by-file changelog.

## Step 4: Verify before committing

Run whatever verification the project actually has (check `package.json` scripts, `Makefile`,
etc.). Common defaults: `pnpm typecheck`, `pnpm lint`, `pnpm build`. If any fail, report the
errors and do not commit until fixed. Skip silently only if the project has none of these set
up.

## Step 5: Stage, commit, clean the tree

Read `references/commit-execution.md` for exactly how to construct the commit so subject and
body never get squashed into one run-on string. Short version: use `git commit -F` with a
temp file for anything with a body (which is every commit), and verify with `git log -1`
afterward that subject and body actually rendered as two separate blocks. If a
`Co-authored-by` trailer is included, double check the angle brackets around the email before
committing, that's the part that actually breaks recognition if missing.

After each commit (or batch of commits for a multi-concern diff), before declaring the task
or session done, always run:

```bash
git status --short
```

Output must be empty. Every remaining file is either committed or intentionally discarded
(`git checkout -- <file>` / `git clean -fd`). No "trivial leftover" exception. See
`references/clean-tree-checklist.md` for the full checklist. An unattended platform (Replit,
CI, etc.) may otherwise auto-commit leftovers with a message that violates every rule above.

## Anti-patterns to reject

Reject and rewrite any commit message (yours or the user's) that:

- Has no scope, i.e. `type: summary` with no `(scope)` and no genuine repo-wide justification
- Has no body at all, i.e. subject-only with nothing explaining the why
- Includes a file that's covered by `.gitignore`
- Cites an ignored or untracked file (like a local rules doc) as the authority for a change,
  instead of paraphrasing the actual rule into the message
- Reads like an exhaustive file-by-file changelog dump instead of a concise explanation
- Has the subject and body run together with no blank line between them
- Contains a literal `\n` or similar escape sequence as visible text instead of a real line
  break
- Contains an em dash, en dash, or emoji anywhere in the subject or body
- Renders a command-line flag or path with a smart-punctuation dash instead of plain ASCII
  hyphens, breaking it if copied and pasted
- Has a `Co-authored-by` trailer missing the angle brackets around the email, this genuinely
  breaks recognition. Wrong: `Co-authored-by: Name email`. Right: `Co-authored-by: Name
  <email>`. Casing (`Co-authored-by` vs `Co-Authored-By`) is case-insensitive per the git
  trailer spec and still works either way, but default to the canonical lowercase-after-C
  form for consistency
- Duplicates a commit that already exists in recent history for the same change
- Isn't written in English
- Contains `phase`, `session`, `iteration`, `step` (including numbered variants)
- Uses past tense instead of imperative, or ends with a period
- Is a generic AI summary instead of describing the real change
- Bundles unrelated changes with no logical connection
- Describes implementation details in the subject instead of the body
- Leaves the working tree dirty after the "done" declaration

## Caveman mode

On "caveman commit", "/caveman-commit", or "terse commit": compress the body to the bare
minimum, one Markdown line or one short bullet stating the why, but never drop it entirely.
Body is still mandatory. Breaking changes, security fixes, migrations, and reverts still get a
fuller body regardless of mode. Same format, scope requirement, and banned words and
characters (em dash, en dash, emoji) still apply. In caveman mode, only output the message as
a code block, don't stage or commit. "stop caveman-commit" or "normal mode" reverts to the
full workflow above.

## Bundled references

- `references/proactive-trigger.md`: full detail for Step 0, the check-in flow.
- `references/staging-and-gitignore.md`: full detail for Step 2, grouping and gitignore safety.
- `references/message-style.md`: full detail for Step 3, subject/body rules and type table.
- `references/commit-execution.md`: full detail for Step 5, how to construct the commit safely.
- `references/examples.md`: worked good and bad examples, including a real failure case.
- `references/strict-mode.md`: fixed commit author, banned-word list, and no-amend rule for
  repos that require it. Read only when strict mode applies.
- `references/clean-tree-checklist.md`: the full end-of-session clean-tree checklist.
