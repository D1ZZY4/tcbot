# Commit Execution Mechanics

Full detail for Step 5 in SKILL.md. This exists because subject and body running together
into one paragraph is a real, recurring failure mode, not a hypothetical one.

## Check for duplicate commits before committing

Before running the actual commit command, check recent history isn't about to get the same
change committed twice:

```bash
git log --oneline -5
git diff --cached --stat
```

If a commit with essentially the same subject and the same file set as the one about to be
made already exists in the last few entries, stop and check what happened instead of
proceeding. This usually means an earlier step already committed the change and the working
tree state wasn't re-checked before starting this one, or the same task got run twice. Re-run
`git status --short` to see what's actually still uncommitted before writing another message
for it.

## Never squash subject and body into one string

A commit message is two blocks separated by a blank line: subject, then body. If they get
concatenated into a single run-on string, the result reads like a wall of text and defeats
the entire point of Conventional Commits.

## Never use literal backslash-n as a stand-in for a real line break

This is a distinct and very common failure: writing `-m "subject\nbody"` with `\n` inside a
plain double-quoted bash string does not produce a newline. Bash does not interpret `\n`
there, it becomes the two literal characters backslash and `n`, sitting right in the commit
message text where a human will read them. If a generated message ever contains a visible
`\n`, `\n\n`, or similar escape sequence as text, that's this bug, not a real newline. Always
use one of the two methods below instead, both of which produce real newline bytes, never a
typed-out escape sequence.

## Method 1: two `-m` flags

Works for short, simple bodies:

```bash
git commit -m "type(scope): summary" -m "body line one

- bullet if needed"
```

Each `-m` becomes its own paragraph, separated by a blank line automatically.

## Method 2: file plus `-F` (preferred for anything multi-line or with bullets)

Safer, since it avoids shell quoting issues entirely:

```bash
cat > /tmp/commit-msg.txt << 'EOF'
type(scope): summary

Body explaining why, in Markdown.
- bullet one
- bullet two
EOF
git commit -F /tmp/commit-msg.txt
```

## Always verify after committing

```bash
git log -1
```

Confirm three things: the subject and body rendered as two visually separate blocks with a
blank line between them, not one run-on paragraph; there's no literal `\n` text sitting
anywhere in the message (that means the escape-sequence bug happened, not a real newline); and
if a `Co-authored-by` trailer is present, the email is wrapped in angle brackets, `<email>`,
since that part is what actually breaks recognition if missing. Casing of the trailer key
itself is case-insensitive per the git trailer spec and works either way, default to
`Co-authored-by` for consistency but it's not a functional bug if it varies. If the brackets
are missing, the commit needs to be amended before moving on (only if not yet pushed; see the
no-amend-after-push rule in `strict-mode.md` when strict mode is active).

## Author identity

In strict mode, set the commit author per `strict-mode.md` before running any of the above,
and verify with `git log -1 --format="%an <%ae>"` before pushing.
