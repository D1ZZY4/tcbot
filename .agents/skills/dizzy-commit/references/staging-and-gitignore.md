# Staging Discipline and Gitignore Safety

Full detail for the staging part of Step 2 in SKILL.md.

## Group by logical concern

Group changed files by concern: one bug fix, one refactor, one feature, one docs update. If
the diff spans unrelated areas, split into multiple commits. Never bundle unrelated changes,
even if asked to "commit everything at once." Warn the user and offer to split; if they
insist, generate one commit per concern anyway.

## Never cite an ignored or untracked file as authority in the message

This is a distinct failure from staging an ignored file, and just as real: writing something
like "per prompt.md § SKILL.md frontmatter" in a commit body, when `prompt.md` lives in a
gitignored folder. The commit itself might be correct, but the citation points at a file that
isn't part of the tracked repo, so anyone who clones it, reviews the commit on GitHub, or
reads `git log` later has no way to verify or even find what's being cited. It reads like a
reference to shared context that doesn't actually exist for them.

Before citing any file as the source of a rule or rationale in a commit message:

```bash
git check-ignore -v <the file being cited>
git ls-files --error-unmatch <the file being cited>
```

- If the file is tracked, citing it by path is fine, anyone with the repo can open it.
- If the file is ignored or untracked, don't cite its path as an external authority. Instead,
  paraphrase the actual rule or reasoning directly into the commit body in plain language, so
  the message is self-contained and makes sense to someone who will never see that file. What
  matters is the substance of the rule, not the specific filename it happened to live in
  locally.
- If the cited file genuinely should be shared context for anyone working on the repo (a spec,
  a style guide, a set of project rules), that's a signal it likely shouldn't be gitignored at
  all, flag that to the user as a separate observation rather than silently working around it.

## Never stage or commit a gitignored file

Before staging anything, check whether it's ignored:

```bash
git check-ignore -v <file>
```

Rules:

- If a file is ignored, it stays out of the commit, full stop. This is true even if its
  content was the source of an edit that landed somewhere else.
- If content originated from an ignored path (for example, a file inside an ignored folder
  was used as the basis for changes made to a tracked file elsewhere), that's fine, the
  tracked result can be committed. But the ignored file itself never gets added, and this
  should be mentioned to the user rather than silently decided either way.
- If something looks like it should be ignored but isn't (a `.gitignore` gap), or looks like
  it shouldn't be ignored but is, flag it and ask instead of guessing.
- Run `git status --short` right before staging, not just at the start of the task, since
  files can appear or change state partway through a session.

## Staging itself

Stage only the files belonging to the current concern (`git add <file>`), not `git add -A`
or `git add .` unless the whole diff genuinely is one concern and has already been checked
against the gitignore rule above.
