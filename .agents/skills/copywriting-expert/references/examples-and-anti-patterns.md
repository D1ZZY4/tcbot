# Examples and Anti-Patterns

Full detail for Step 5 in SKILL.md. Consolidated good/bad pairs across component types, check
new or audited copy against these patterns before finalizing.

## Buttons

| Weak | Better | Why |
|---|---|---|
| OK | Delete project | Names the actual action |
| Submit | Send invite | Specific verb, not generic |
| Yes / No | Delete / Cancel | Clear opposites naming the action |

## Error messages

See the full table in `error-messages.md`. Core pattern: state the problem plainly, explain
why when useful, say what to do next when there's something to do, never blame the user.

## Empty states

| Weak | Better | Why |
|---|---|---|
| No items yet | Create your first project to get started | Orients and prompts action |
| No results | No results match your filters. Clear filters? | Distinguishes filtered-empty from genuinely-empty |
| (blank, no copy at all) | You've archived all your tasks | Acknowledges the actual situation |

## Confirmation dialogs

| Weak | Better | Why |
|---|---|---|
| Are you sure? | This will permanently delete the project and all its files. This can't be undone. | States the actual consequence |
| OK / Cancel | Delete project / Cancel | Confirm button names the action |
| Remove member? | Remove Aby from this project? They'll lose access immediately. | Names who and what's affected |

## A full before/after, combining multiple fixes at once

**Before:**
```
Title: Confirm
Body: Are you sure you want to do this? This action is permanent, it cannot be undone.
Buttons: Yes / No
```

Three problems: generic title and body that could apply to any action, buttons that don't
name the action, and (not shown literally here since this skill won't paste one even as an
illustration) the original draft used an em dash between "permanent" and "it cannot be
undone" instead of the comma shown above.

**After:**
```
Title: Delete this project?
Body: This will permanently delete "Q3 Roadmap" and all 12 files inside it. This can't be
undone.
Buttons: Delete project / Cancel
```

## Anti-patterns, consolidated

- **Vague generic copy** that could apply to any situation ("Something went wrong", "Are you
  sure?") instead of naming the specific thing that happened.
- **Blaming language** in error copy ("You entered an invalid value") instead of neutral
  framing ("That value doesn't look right").
- **Technical leakage**: internal error codes, stack traces, or system terminology surfacing
  directly in user-facing text without translation into plain language.
- **Inconsistent register**: mixing formal and casual tone within the same flow, or switching
  conventions (Title Case in one dialog, sentence case in the next) without a documented
  reason.
- **Unverified language-specific word choice**: shipping a translation or a specific term
  without checking it against the authoritative source for that language, see
  `language-and-vocabulary-verification.md`.
- **Em dashes**, anywhere, ever. See `formatting-and-punctuation.md`.
- **Confirmation fatigue**: dialogs on every minor action train users to click through without
  reading, which defeats the one dialog that actually needs their attention.
- **Copy as an afterthought**: writing the UI first and filling in placeholder text like "Lorem
  ipsum" or "TODO: copy" that ships unreviewed, instead of treating copy as part of the
  feature from the start.
