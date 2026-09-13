# Changelog Style Rules

This file defines how `CHANGELOG.md` entries are written: professional,
human wording that tells the reader what changed and why it matters.
No tool names, no process narration, no implementation jargon. Code
conventions live in [`code-style.md`](code-style.md), and comment and
Markdown conventions live in [`comment-style.md`](comment-style.md).

---

## Voice

Write like a professional release note, never like generated filler:

- One idea per bullet. One bullet never covers two changes.
- Short sentences. Reader perspective first: what changed for the
  operator, translator, or contributor, and why it matters.
- Say what changed and what it means. Never describe how the work
  was done.

## Banned Language

Never use in an entry:

- Tool names: `ruff`, `pyright`, `pytest`, `test suite`, `full suite`,
  test counts (`37 new tests`, `92 passed`).
- Process narration: `Verified`, `verified against`, `audit`,
  `zero findings`, `golden`, `harness`, `stub`, `fake`, `compileall`.
- Implementation jargon: placeholder names (`{window}`, `{limit}`),
  `Safe`, `plain=True`, `pre()`, internal function names, file-local
  identifiers. Name the user-visible outcome instead.
- Em dashes (U+2014) anywhere; see the character rule in
  [`comment-style.md`](comment-style.md#em-dashes).

## What Stays

- File paths in parentheses after the bold lead, as the audit trail.
- Behavior-change callouts where behavior actually changed
  (`Behavior changes: ...`); silence means nothing user-visible changed.
- Specific impact notes that help upgrade decisions: labels, callbacks,
  and keyboard shapes unchanged; old callbacks keep working; in-flight
  keyboards keep working; rank safety unchanged.
- Numbers that are behavior facts: limits, counts, timeouts, thresholds.

## Shape

```markdown
- **What changed, plainly** (`paths/touched.py`, `i18n/en-US/x.toml`): two
  or three short sentences. What it does now. Why it matters or what
  to watch for.
```

Good:

```markdown
- **Warn auto-ban retries after total enforcement failure** (`warning_flow.py`):
  the trigger is now `>=` so a fully-failed fan-out retries on the next
  warn instead of wedging. Docs updated.
```

Bad (process narration, jargon, filler):

```markdown
- **Warn auto-ban trigger hardened with strict mini-markup plus golden
  regression** (`warning_flow.py`, `tests/test_i18n.py`): the `>=` trigger
  verified via 224-case old-vs-new sweep with zero mismatches; templates
  stay raw with `{window}` Safe passthrough. Verified: Ruff, Pyright,
  full suite green.
```

## Workflow

1. Add the entry under `[Unreleased]` in the matching section
   (`Added`, `Changed`, `Fixed`, `Removed`, `Documentation`).
2. Never rewrite released version sections; history is immutable.
3. Validate with `git diff --check` and re-read the entry aloud: if a
   sentence only proves work happened instead of informing the reader,
   delete it.
