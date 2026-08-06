---
name: copywriting-expert
description: >
  Write or audit user-facing UI copy: buttons, labels, empty states, error messages,
  tooltips, form text, confirmation dialogs, toasts, and onboarding text. Use proactively,
  not only when explicitly asked to write copy. Trigger any time a feature is being built
  or reviewed that adds any user-facing text, even when copy is incidental to the task (a
  new button, a new validation message, a new empty state), and any time existing copy is
  being audited for voice, tone, clarity, or grammatical correctness. Applies natively in any
  project. If the project has its own copywriting source of truth (a design system doc, a
  content style guide), that takes precedence over the general defaults here, check for one
  first.
---

# Copywriting Expert

This file is the workflow index. Details live in `references/`, load the specific file for
the step or component type you're on rather than guessing.

## Step 0: Check for a project-specific source of truth

Read `references/project-source-of-truth.md` for the full check. Short version: look for a
project's own content style guide or copywriting doc before applying the general defaults
below, common locations include a design system's content docs, a `CONTRIBUTING.md` section,
or a `docs/content-style.md`-style file. If one exists, it overrides anything here that it
addresses directly. If it's silent on something, fall back to the defaults in this skill.

## Step 1: Voice and tone

Read `references/voice-and-tone.md`. Short version: clear over clever, plain language over
jargon, active voice, address the user directly, and match tone to stakes (light for a
success toast, serious for a destructive-action warning).

## Step 2: Write for the component type

Different UI surfaces need different copy patterns:

- **Buttons and labels**: `references/ui-component-copy.md`
- **Error messages**: `references/error-messages.md`
- **Empty states**: `references/empty-states.md`
- **Confirmation and destructive-action dialogs**: `references/confirmation-dialogs.md`
- **Accessibility and localization**: `references/accessibility-and-localization.md`

## Step 3: Verify the language itself, don't guess

Read `references/language-and-vocabulary-verification.md`. This is the step most copy
workflows skip and it matters most: no single training corpus is a complete, authoritative
dictionary for any language, including English. When a word choice, spelling, idiom, loanword,
or grammatical construction in the target language is anything less than certain, look it up
against an actual authoritative source for that language rather than going with what feels
right. Different languages have different authoritative sources (KBBI for Indonesian, a
proper dictionary for English, and so on), the reference file covers how to find and use the
right one per language.

## Step 4: Formatting and punctuation

Read `references/formatting-and-punctuation.md`. This includes an explicit, absolute rule:
no em dashes anywhere in UI copy, under any circumstance. En dashes are allowed when used
correctly as punctuation. Full detail and the rest of the punctuation rules (capitalization,
ellipses, Oxford comma policy) are in that file.

## Step 5: Check against examples and anti-patterns

Read `references/examples-and-anti-patterns.md` for worked good/bad examples across component
types before finalizing anything.

## Anti-patterns to reject

- Writing or approving copy in a language without verifying uncertain vocabulary against an
  actual authoritative source for that language
- Any em dash, anywhere in UI copy
- Blaming the user in error copy ("You entered an invalid email") instead of stating the
  problem neutrally ("That email address doesn't look right")
- A destructive-action dialog whose confirm button just says "OK" or "Confirm" instead of
  naming the actual action ("Delete project", "Remove member")
- Technical jargon or internal system terms leaking into user-facing error messages
- Treating copy as an afterthought bolted onto a finished feature instead of part of the
  feature itself

## Bundled references

- `references/project-source-of-truth.md`: checking for and deferring to a project's own
  content style guide.
- `references/voice-and-tone.md`: core voice principles and how tone shifts with stakes.
- `references/ui-component-copy.md`: buttons, labels, tooltips, form text.
- `references/error-messages.md`: how to write an error message that actually helps.
- `references/empty-states.md`: what an empty state needs to do beyond saying "nothing here".
- `references/confirmation-dialogs.md`: confirmation and destructive-action copy.
- `references/accessibility-and-localization.md`: accessible names, status copy, and localization
  constraints.
- `references/language-and-vocabulary-verification.md`: verifying word choice and grammar
  against authoritative per-language sources instead of guessing.
- `references/formatting-and-punctuation.md`: the em dash ban and other punctuation rules.
- `references/examples-and-anti-patterns.md`: worked good/bad examples across component types.
