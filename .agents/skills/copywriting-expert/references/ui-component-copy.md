# UI Component Copy

Full detail for buttons, labels, tooltips, and form text in Step 2 of SKILL.md.

## Buttons

- Lead with a verb naming the actual action: "Save changes", "Delete project", "Send invite",
  not "OK", "Submit", or "Yes" for anything beyond the most trivial, unambiguous action.
- Keep it to 1 to 3 words when possible, buttons aren't sentences. If the action genuinely
  needs more context to be unambiguous, that context belongs in the surrounding text or the
  dialog body, not crammed into the button.
- The primary and secondary buttons in a pair should read as clear opposites at a glance:
  "Delete" and "Cancel" work, "Delete" and "Go back" is slightly weaker but fine, "Delete" and
  "No" is too vague about what "No" refers to.
- Never use the same label for buttons that do different things in different contexts within
  the same flow, "Continue" meaning something different on two different screens confuses
  users who are pattern-matching on the label, not reading closely each time.

## Labels

- Name the field by what it is, not by an instruction about it: "Email" not "Enter your
  email". The placeholder or helper text is where instructions or format hints go, not the
  label itself.
- Keep required/optional marking consistent across the whole form: either mark required
  fields or mark optional fields, don't do both inconsistently in the same form.
- Avoid abbreviations unless they're truly universal in context ("ZIP" is fine for a US
  address form, an internal system abbreviation is not).

## Tooltips

- A tooltip should add information that isn't already visible, not restate the label. A
  tooltip on a button labeled "Archive" that just says "Archives the item" adds nothing, one
  that says "Moves it out of your active list without deleting it, you can restore it later"
  actually helps.
- Keep tooltips short enough to read in the time a cursor naturally hovers, one sentence in
  most cases, two only when genuinely necessary.
- Don't use a tooltip to hide information that should be visible by default. If something is
  important enough that most users need to know it before acting, it belongs in visible text,
  not behind a hover state some users will never trigger.

## Form text (placeholders, helper text, validation)

- **Placeholders** show a format example, not an instruction: "you@example.com" is a good
  placeholder for an email field, "Enter your email address" is not, that's what the label is
  for. Placeholders disappear the moment the user starts typing, so they should never contain
  information the user needs to remember.
- **Helper text** (persistent text below a field) is for format requirements or context that
  stays relevant while the user is filling out the field: "Must be at least 8 characters",
  "This will be visible to other members."
- **Inline validation** should confirm success as clearly as it flags failure. A field that
  silently turns green isn't as reassuring as one that briefly shows "Looks good" alongside
  the visual change, especially for fields where the format isn't obviously self-evident.
- Validation messages state the actual problem and, where possible, the fix: "Password needs
  at least one number" not "Invalid password." See `error-messages.md` for the full pattern.
