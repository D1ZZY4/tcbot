# Voice and Tone

Full detail for Step 1 in SKILL.md.

## Core principles

- **Clear over clever.** A pun or a clever turn of phrase that makes someone pause to decode
  it has failed at the actual job of UI copy, which is to be understood instantly. Save
  personality for places where a moment of delight doesn't cost comprehension speed (an empty
  state, a success confirmation), never in a spot where the user needs to act quickly (an
  error, a form label, a destructive-action warning).
- **Plain language over jargon.** Write for someone encountering the concept for the first
  time, not for someone who already knows the internal name for a feature. If an internal or
  technical term must appear, define it in context rather than assuming familiarity.
- **Active voice, direct address.** "You can't undo this" reads faster and feels more honest
  than "This action cannot be undone." Speak to the user as "you", not in the passive third
  person, unless the project's own style guide specifically calls for a different register.
  See `project-source-of-truth.md`.
- **Say what happens, not what the system does internally.** "Your changes are saved" not
  "The save operation completed successfully." The user cares about the outcome, not the
  mechanism.
- **Be specific, not generic.** "3 files couldn't be uploaded" tells the user something
  actionable, "Something went wrong" doesn't. Specificity is almost always worth the extra
  words, within reason, see `error-messages.md` for how far to take this.

## Tone shifts with stakes, not with mood

Tone isn't a fixed personality applied uniformly everywhere, it should track how much is at
stake for the user in that moment:

- **Low stakes** (a success toast, an empty state before any data exists): warmth and light
  personality are fine, this is where a product's voice gets to show character.
- **Medium stakes** (a form validation message, a tooltip): neutral and helpful, get out of
  the way, don't editorialize.
- **High stakes** (an error that blocks progress, a destructive-action confirmation, a
  security warning): serious, precise, zero cleverness. A joke or a casual aside next to "This
  will permanently delete your account" undermines trust at exactly the moment trust matters
  most.

Never let a consistent brand voice override this scaling. A brand that's playful everywhere
else should still go straight and serious the moment stakes go up.

## Sentence case, not Title Case, by default

Unless a project's style guide specifies otherwise, use sentence case for UI text: buttons,
headings, labels, and menu items capitalize only the first word and proper nouns ("Save
changes", not "Save Changes"). This is the prevailing modern convention across most design
systems, but check `project-source-of-truth.md` first since some codebases still use Title
Case by established convention and consistency with existing copy matters more than which
convention is objectively more modern.

## Consistency with existing copy in the same product

Before writing new copy, check how similar situations are already phrased elsewhere in the
same product (search the codebase for similar strings). New copy that's individually well
written but inconsistent with the existing voice reads as jarring and unprofessional, worse
than copy that's slightly less polished but consistent.
