# Formatting and Punctuation

Full detail for Step 4 in SKILL.md.

## No em dashes, ever, explicit and absolute

Never use an em dash (Unicode U+2014, the long dash) anywhere in UI copy, in any language,
under any circumstance. Not in buttons, not in error messages, not in empty states, not in
tooltips, not in confirmation dialogs, not in draft copy, not in a "just this once, it reads
better here" exception. When a sentence seems to want an em dash, restructure it instead:

- Use a period and split into two sentences.
- Use a comma if the pause is light.
- Use a colon if what follows explains or elaborates on what came before.
- Use parentheses if it's a genuine aside.

An en dash (U+2013) is allowed when it has its own meaning, such as a numeric range
("9:00–17:00") or a relationship ("input–output"). Do not use an en dash where a regular
ASCII hyphen is required in a technical string, identifier, command, or flag.

Example: "Your file was too large, try compressing it first" instead of a version built
around an em dash. If a rewrite keeps reaching for an em dash no matter how it's restructured,
that's usually a sign the sentence is trying to do too much, split it into two shorter
sentences instead.

## Sentence case for UI text

Capitalize only the first word and proper nouns in buttons, labels, headings, and menu items,
unless the project's own style guide specifies Title Case. See `voice-and-tone.md` and
`project-source-of-truth.md`.

## Ellipses

Use an ellipsis (three periods, or the single-character variant) only to indicate an action
that requires further input before completing, most commonly on a button or menu item that
opens a dialog or requires more steps: "Export...", "Rename...". Don't use an ellipsis for
dramatic pause or trailing-off effect in UI copy, that's a stylistic device for prose, not a
functional signal for an interface.

## Oxford comma

Use the Oxford comma (the comma before "and" or "or" in a list of three or more items) for
clarity: "Save, export, or discard your changes." This is the same rule as English formal
writing generally, and it prevents genuine ambiguity in a way that matters more in short UI
copy than in longer prose, where there's less surrounding context to disambiguate.

## Exclamation points, sparingly

Reserve exclamation points for genuine, warranted enthusiasm (a first-time success moment, a
milestone), not as a default energy booster on routine confirmations. A save confirmation
that fires on every single save doesn't need "Saved!" every time, "Saved" is enough, save the
exclamation point for something that's actually a bit special.

## Numbers

Spell out numbers zero through nine in prose-style copy, use numerals for 10 and above,
except when a numeral is more scannable in context (counts, statistics, anything in a table
or a badge) or the project's own convention differs. Always use numerals for anything the
user needs to scan quickly rather than read as prose (a file count, a price, a percentage).

## Contractions

Contractions ("don't", "can't", "you'll") are generally fine and often preferable for UI copy
since they read as more natural and conversational, matching the direct-address principle in
`voice-and-tone.md`. The exception is in formal, high-stakes copy (legal text, security
warnings, an irreversible-action confirmation) where the slightly more formal uncontracted
form can underscore that the moment matters.
