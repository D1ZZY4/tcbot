# Empty States

Full detail for empty states in Step 2 of SKILL.md.

## An empty state has to do more than announce absence

"No items yet" is technically accurate and almost entirely useless. A good empty state
answers three questions in order of priority:

1. **What would normally be here?** Orient the user to what this space is for, especially
   important for a section they haven't encountered before.
2. **Why is it empty right now?** Distinguish between genuinely-new-and-nothing-created-yet,
   filtered-to-nothing, and an error state that happens to look empty. These need different
   copy, see below.
3. **What can the user do about it, if anything?** If there's a clear next action (create the
   first item, adjust a filter, invite a teammate), say it and make it actionable, don't just
   describe the action in text if a button can do it directly.

## Different kinds of empty aren't the same

- **Genuinely new, nothing created yet**: this is the friendliest empty state, an opportunity
  to orient and prompt the first action. "Create your first project to get started" with a
  clear call-to-action button.
- **Filtered or searched to zero results**: the user had content, then took an action that
  hid it all. Say that plainly and offer a way back: "No results match your filters" with a
  visible way to clear them, not a generic empty-state illustration that implies there was
  never anything here.
- **Emptied by the user's own action** (archived everything, deleted everything): acknowledge
  what happened rather than treating it identically to brand-new: "You've archived all your
  tasks" reads very differently from "No tasks yet" even though the visible state is the same.
- **An error masquerading as empty** (a failed fetch that renders as zero items): this is not
  actually an empty state and shouldn't use empty-state copy at all, it needs error copy, see
  `error-messages.md`. Conflating a fetch failure with genuine emptiness hides real problems
  from both users and whoever's debugging support tickets later.

## Keep the call-to-action specific

"Get started" as a button label is weaker than "Create your first project", the second tells
the user exactly what will happen before they click. Prefer the specific version whenever the
empty state has one clear primary action.

## Don't overdo the personality

Empty states are a common place for products to lean into playful copy ("Nothing to see
here... yet!"), which is fine in genuinely low-stakes contexts but should still clearly answer
the three questions above. Personality that replaces the actual information the user needs
(what is this, why is it empty, what can I do) has failed at the job even if it's charming.
