---
name: dizzy-commit
description: >
  Guide safe, repository-aware Git commits and pushes, using Conventional Commits when required
  by the repository or requested by the user. When work is uncommitted at the end of a task,
  inspect and report it, but never commit or discard changes automatically.
---

# Dizzy Commit

Everything this skill needs is bundled here. No separate commit-policy file is required.
This file is the workflow index. Details live in `references/`, load the specific file for
the step you're on rather than guessing. Inspect the repository's own tooling, contribution
rules, and commit policy before applying message or verification assumptions.

## Policy precedence

Read `references/policy-configuration.md` before applying message rules. Resolve policy in this
order:

1. Host or system safety constraints
2. Repository policy and contribution guide
3. Explicit user preferences or instructions
4. This skill's portable defaults

Project-specific author, branch, remote, language, scope, body, or prohibited-word rules are
policy inputs, not universal defaults. Never invent them or silently change Git configuration to
satisfy them.

## Safety boundary

Inspecting a dirty working tree is always allowed. Staging, committing, restoring, deleting,
or cleaning files requires an explicit user request or confirmation. Treat pre-existing changes
as user-owned unless ownership is clear. Never use `git checkout -- <file>` or `git clean -fd`
to force a clean tree.

## Two modes

- **Default mode** (used automatically, always): the rules in `references/message-style.md`.
- **Strict mode**: triggered when the user says "strict commit", "strict mode", or explicitly
  asks to enforce a fixed commit author or banned-word rules for a repo. Read
  `references/strict-mode.md` for the extra constraints and apply them on top of default mode,
  not instead of it.

If the user explicitly requests a commit but does not specify strict mode, use the default
rules. If no commit request was made, inspect and report dirty changes without staging,
committing, restoring, or deleting them.

## Step 0: Inspect proactively, mutate only with approval

Don't wait for the exact word "commit" or the skill name. Read `references/proactive-trigger.md`
for the full inspection and confirmation flow. If the tree is dirty, inspect ownership and
report the changes. Ask whether to commit if the user has not already requested it. Never treat
a dirty tree as permission to stage, commit, restore, or delete files.

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
type table, and the list of things that never belong in a commit message. Apply scope, body,
language, punctuation, and prohibited-word requirements only when the resolved repository or
user policy requires them. The body should read like a senior developer wrote it, not like an
enumerated file-by-file changelog.

## Step 4: Verify before committing

Detect the repository's project type, package manager, lockfile, and declared scripts before
running verification. Check `package.json`, `Makefile`, `pyproject.toml`, `Cargo.toml`, or
equivalent project configuration as applicable. Run only commands that are actually declared
or clearly supported by the repository. Do not assume pnpm. If verification fails, report the
errors and do not commit until fixed. If no verification command exists, say that verification
was unavailable.

## Step 5: Stage and commit only after explicit approval

Read `references/commit-execution.md` for exactly how to construct the commit so subject and
body never get squashed into one run-on string, and read `references/push-and-upstream.md` before
pushing. Short version: use `git commit -F` with a temp file when the resolved policy requires a
body, and verify with `git log -1` afterward that the subject and body rendered correctly. If a
`Co-authored-by` trailer is included, double check the angle brackets around the email before
committing, that's the part that actually breaks recognition if missing.

Stage and commit only after the user explicitly asks for it or confirms the check-in request.
Before staging, distinguish changes made during this task from pre-existing user changes. If
ownership is unclear, stop and ask. Never use restore or clean commands to force a clean tree.
After each commit, verify the requested changes and run:

```bash
git status --short
```

If files remain, report them and their ownership. A non-empty tree is acceptable when it
contains pre-existing user work or changes the user has intentionally kept. Never run
`git checkout -- <file>` or `git clean -fd` without explicit, file-specific confirmation.
See `references/clean-tree-checklist.md` for the full checklist.

## Anti-patterns to reject

Reject and rewrite any commit message (yours or the user's) that:

- Has no scope when the resolved commit policy requires one, or uses a misleading scope
- Has no body when the resolved commit policy requires one, or omits the why for a non-trivial
  change
- Includes a file that's covered by `.gitignore`
- Cites an ignored or untracked file (like a local rules doc) as the authority for a change,
  instead of paraphrasing the actual rule into the message
- Reads like an exhaustive file-by-file changelog dump instead of a concise explanation
- Has the subject and body run together with no blank line between them
- Contains a literal `\n` or similar escape sequence as visible text instead of a real line
  break
- Contains an em dash or emoji when the resolved punctuation policy forbids it
- Replaces the plain ASCII hyphens required by a command-line flag or path with a smart
  punctuation dash, breaking it if copied and pasted. An en dash is allowed as normal
  punctuation outside literal commands, flags, and paths.
- Has a `Co-authored-by` trailer missing the angle brackets around the email, this genuinely
  breaks recognition. Wrong: `Co-authored-by: Name email`. Right: `Co-authored-by: Name
  <email>`. Casing (`Co-authored-by` vs `Co-Authored-By`) is case-insensitive per the git
  trailer spec and still works either way, but default to the canonical lowercase-after-C
  form for consistency
- Duplicates a commit that already exists in recent history for the same change
- Violates the resolved commit language policy
- Contains a configured prohibited word or phrase
- Uses past tense instead of imperative, or ends with a period
- Is a generic AI summary instead of describing the real change
- Bundles unrelated changes with no logical connection
- Describes implementation details in the subject instead of the body
- Leaves agent-owned changes dirty after the "done" declaration, while pre-existing user work
  must be preserved and reported rather than cleaned

## Caveman mode

On "caveman commit", "/caveman-commit", or "terse commit": compress a required body to the bare
minimum, one Markdown line or one short bullet stating the why. Never omit the body when the
resolved policy or change complexity requires it. Breaking changes, security fixes, migrations,
and reverts still get a fuller body regardless of mode. Apply the resolved format, scope,
language, punctuation, and prohibited-word policy. An en dash is allowed as normal punctuation,
but literal commands, flags, and paths must retain their plain ASCII hyphens. In caveman mode,
only output the message as a code block, don't stage or commit. "stop caveman-commit" or
"normal mode" reverts to the full workflow above.

## Bundled references

- `references/proactive-trigger.md`: full detail for Step 0, the check-in flow.
- `references/policy-configuration.md`: portable defaults and project/user policy precedence.
- `references/staging-and-gitignore.md`: full detail for Step 2, grouping and gitignore safety.
- `references/host-adapters.md`: optional Git host and upstream conventions.
- `references/message-style.md`: full detail for Step 3, subject/body rules and type table.
- `references/commit-execution.md`: full detail for Step 5, how to construct the commit safely.
- `references/push-and-upstream.md`: remote, upstream, branch, and push safety.
- `references/examples.md`: worked good and bad examples, including a real failure case.
- `references/strict-mode.md`: policy-driven strict checks and no-amend rule for
  repos that require it. Read only when strict mode applies.
- `references/clean-tree-checklist.md`: the full end-of-session clean-tree checklist.
