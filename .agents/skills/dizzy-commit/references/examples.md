# Worked Examples

## Good, default mode

```
feat(api): add GET /users/:id/profile

Mobile client needs profile data without the full user payload
to reduce LTE bandwidth on cold-launch screens.

Closes #128
```

## Good, specific agent identity in the co-author trailer

```
fix(ui): count free-tier oauth connections on providers list

Free-tier cards hardcoded apikey for stats and toggle, so oauth
connections were invisible on the providers list despite showing
on the detail page. Use dualAuthTypes per provider instead.

Co-authored-by: Agent model/version <provider-issued-address>
```

Naming the specific model and version, not just a bare tool name, tells a future reader
which agent produced the commit, useful when debugging model-specific patterns later.
A non-default configuration (extended context, a specific mode) can go in parentheses after
the name when it's actually known, never guessed.

## Good, strict mode

Two unrelated dark-mode fixes, split into two commits. See `strict-mode.md` for the author
and banned-word rules applied here.

```
fix(button): dark mode contrast on danger variant

Add `dark:text-[#f07060]` and `dark:border-[#d44a30]` to danger variant.

Aligns with `--status-unstable-text` and `--status-unstable-border` dark
variants already defined in `globals.css`.
```

```
fix(info-tab): status tokens for stable/bug colors

- `text-[var(--color-stable)]` -> `text-[var(--status-stable-text)]`
- `bg-[var(--color-unstable)]` -> `bg-[var(--status-unstable-border)]`

Fixes dark mode contrast. The raw color vars have no dark override.
```

## Bad: bundled and policy-violating

```
refactor: combine security, bug, and accessibility changes

Security:
- Remove spam-protection note from FeedbackForm
- Add URL scheme guards for download_link/donate_link

Bug fixes:
- Wire filter variants into a brand filter
- Replace inconsistent shape tokens across several components
...
```

17 unrelated changes in one commit, with no useful reason. Split it into one focused commit per
concern instead. A missing scope or a prohibited word is also a rejection only when the resolved
repository policy requires that rule.

## Bad: subject and body run together, changelog-dump body (real failure mode)

```
docs(repo): sync references after a documentation rename Update
references across several README files and register the replacement guide
in the documentation index - Remove redundant notes already integrated
elsewhere
```

Broken in three ways: no blank line between subject and body, so it reads as one run-on
sentence; the body lists individual files instead of the actual change; and it never checked
whether the source directory was ignored before including its content.

Fixed version, using the `-F` file method from `commit-execution.md` to guarantee real
separation:

```
docs(docs): sync references after a documentation rename

Update references across the affected documentation and register the
replacement guide in the relevant documentation index.

Remove redundant local notes that were already integrated elsewhere.
```

## Bad: wall-of-text body (real failure mode)

```
fix(skills): add missing references/ line to 3 README.md structure trees

  Several documentation indexes omitted a references/ directory that
  the project rules already declare.

Co-Authored-By: Agent model/version <provider-issued-address>
```

The real bug here is the body: three separate facts about the missing
directory, the established pattern, and the fix are crammed into one dense sentence
instead of Markdown bullets. The trailer's `Co-Authored-By` casing looks off compared to the
canonical `Co-authored-by`, but it's not actually broken, git trailer keys are
case-insensitive, so this still gets recognized. Still worth matching the canonical casing for
consistency. Fixed version:

```
fix(skills): add missing references/ to 3 README trees

  Several documentation indexes omitted references/, which the project
  rules already declare.

  - One existing module provides the established directory pattern
  - Other modules only need a placeholder until content is added

  Synced the documentation indexes to match the project folder maps.

Co-authored-by: Agent model/version <provider-issued-address>
```

## Bad: en dash replaces the hyphens in a command flag

```
docs(readme): add LFS clone instructions

Recommended clone command with [en dash]recurse-submodules or git lfs
clone. Users without git-lfs can still use the skill docs, only
binary assets are affected.
```

The problem is not using an en dash as punctuation. The flag incorrectly replaces the leading
two ASCII hyphens of `--recurse-submodules` with one en dash (U+2013), shown above as
`[en dash]` so the broken character is clear without presenting it as a valid command. Copied
straight into a terminal, that replacement fails to parse as the flag it is supposed to be.
The fixed version preserves the plain ASCII hyphens:

```
docs(readme): add LFS clone instructions

Recommend cloning with --recurse-submodules or using git lfs clone.
Users without git-lfs can still read the skill docs, only binary
assets are affected.
```
