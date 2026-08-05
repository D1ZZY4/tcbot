# Worked Examples

## Good, default mode

```
feat(api): add GET /users/:id/profile

Mobile client needs profile data without the full user payload
to reduce LTE bandwidth on cold-launch screens.

Closes #128
```

## Good, specific model name in the co-author trailer

```
fix(ui): count free-tier oauth connections on providers list

Free-tier cards hardcoded apikey for stats and toggle, so oauth
connections were invisible on the providers list despite showing
on the detail page. Use dualAuthTypes per provider instead.

Co-authored-by: Claude Sonnet 5 <noreply@anthropic.com>
```

Naming the specific model and version, not just a bare "Claude", tells a future reader
exactly which model produced the commit, useful when debugging model-specific patterns later.
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

## Bad: bundled, plan-flavored, banned words

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

17 unrelated changes in one commit, no scope, contains "Phase 3." Split into one focused
commit per concern instead, each with its own scope.

## Bad: subject and body run together, changelog-dump body (real failure mode)

```
docs(repo): sync references after LICENSE rename and NFC doc integration Update LICENSE.md to LICENSE in 8 README files following the a270f09 rename - Register nfc-oos-post-port.md in port-rom AGENTS.md, REFERENCE.md, and README.md file maps - Delete integrated prompt/info-1.md and prompt/info-2.md
```

Broken in three ways: no blank line between subject and body, so it reads as one run-on
sentence; the body lists individual files instead of the actual change; and it never checked
whether `prompt/` was gitignored before including content sourced from it.

Fixed version, using the `-F` file method from `commit-execution.md` to guarantee real
separation:

```
docs(repo): sync references after LICENSE rename

Update LICENSE.md references to LICENSE across READMEs and register
the new NFC port doc in the port-rom file maps, following a270f09.

Drops the now-redundant prompt/info-1.md and info-2.md content that
was already merged elsewhere.
```

## Bad: wall-of-text body (real failure mode)

```
fix(skills): add missing references/ line to 3 README.md structure trees

rom, kernel, and debug README.md structure listings omitted the references/ directory that AGENTS.md for those domains already declares and that disk has (selinux-repair with 17 files, or a .gitkeep placeholder for the other two). Synced README.md to match AGENTS.md folder maps.

Co-Authored-By: Claude <noreply@anthropic.com>
```

The real bug here is the body: three separate facts (what's missing, what selinux-repair
already has as the working pattern, what the fix does) crammed into one dense sentence
instead of Markdown bullets. The trailer's `Co-Authored-By` casing looks off compared to the
canonical `Co-authored-by`, but it's not actually broken, git trailer keys are
case-insensitive, so this still gets recognized. Still worth matching the canonical casing for
consistency. Fixed version:

```
fix(skills): add missing references/ to 3 README trees

rom, kernel, and debug README.md structure listings omitted
references/, which their AGENTS.md already declares.

- selinux-repair has 17 files in references/, used as the pattern
- rom, kernel, debug only need a .gitkeep placeholder for now

Synced all three README.md files to match their AGENTS.md folder
maps.

Co-authored-by: Claude <noreply@anthropic.com>
```

## Bad: en dash breaks a copy-pasted command

```
docs(readme): add LFS clone instructions

Recommended clone command with [en dash]recurse-submodules or git lfs
clone. Users without git-lfs can still use the skill docs, only
binary assets are affected.
```

The flag rendered with an en dash (U+2013) standing in for the leading two hyphens of
`--recurse-submodules`, shown above as `[en dash]` since the literal character shouldn't be
pasted even in an illustration of the bug. Copied straight into a terminal, an en dash there
fails to parse as the flag it's supposed to be. Fixed version uses plain ASCII hyphens:

```
docs(readme): add LFS clone instructions

Recommend cloning with --recurse-submodules or using git lfs clone.
Users without git-lfs can still read the skill docs, only binary
assets are affected.
```
