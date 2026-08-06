# Confirmation and Destructive-Action Dialogs

Full detail for confirmation dialogs in Step 2 of SKILL.md.

## Name the specific consequence, not just the action

A confirmation dialog exists to make sure the user understands what's about to happen before
it happens, irreversibly in many cases. State the actual consequence, not a generic warning:

- Weak: "Are you sure?"
- Better: "This will permanently delete the project and all its files. This can't be undone."

Generic confirmation copy trains users to click through without reading, since it never tells
them anything they didn't already know from clicking the button. Specific copy earns the
pause.

## The confirm button names the action, never just "OK" or "Yes"

- Weak: "OK" / "Cancel"
- Better: "Delete project" / "Cancel"

This matters for two reasons: it reduces the chance of an accidental confirm click (reading
"Delete project" registers differently than reading "OK"), and it means the dialog is
understandable on its own even if someone only skims the buttons without reading the body
text.

## Scale the friction to the severity and reversibility

- **Reversible, low-stakes** (archiving something that can be restored): a lightweight
  confirmation, sometimes none at all if the action is easily undoable via a toast with an
  "Undo" option instead of a blocking dialog.
- **Reversible, but not obviously so**: confirm, and say that it's reversible and how ("You
  can restore this from the trash within 30 days").
- **Irreversible, low-impact** (removing yourself from a shared doc you can rejoin): a
  standard confirmation naming the consequence.
- **Irreversible, high-impact** (deleting an account, removing a team's only admin, deleting
  production data): the highest friction available, consider requiring the user to type the
  resource's name or a confirmation phrase, not just click a button, and state consequences in
  full, including anything else that gets affected (other users losing access, data that
  can't be recovered, billing implications).

## Don't confirm things that don't need confirming

Overusing confirmation dialogs for low-stakes, easily reversible actions trains users to
click through them without reading, which defeats the purpose for the times it actually
matters. Reserve dialogs for genuinely consequential actions, use lighter patterns (an undo
toast, an inline warning) for everything else.

## State who or what else is affected, not just the immediate object

"Delete this project" undersells the stakes if deleting it also removes 4 other people's
access and 200 files. When a destructive action has a blast radius beyond the object being
acted on, name that explicitly: "This will delete the project and remove access for all 4
members."
