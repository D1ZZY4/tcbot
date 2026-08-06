# Proactive Trigger Conditions

Full detail for Step 0 in SKILL.md. This is the part the original version of this skill was
missing, it only activated on explicit trigger words ("diagram", "visualize", "map out"),
which meant it never fired on its own even when a diagram was clearly the better answer.

## Reach for a diagram without being asked when

- **Explaining architecture or system structure**: describing how services, components, or
  modules relate to each other. A paragraph of "the frontend calls the API which calls the
  database which then notifies the queue" is exactly the shape a diagram communicates faster
  and more precisely than prose.
- **Explaining a flow over time**: API request/response cycles, auth flows, event sequences,
  anything where order and timing matter. Sequence diagrams exist specifically for this.
- **Explaining a database schema or data model**: table relationships, foreign keys,
  cardinality. Prose descriptions of schemas are notoriously hard to follow, an ERD is not.
- **Explaining a decision process, algorithm, or user journey**: anything with branches,
  conditions, or a "then this happens, unless that happens" structure.
- **Designing or documenting a domain model**: classes, their attributes, methods, and how
  they relate (inheritance, composition, association).
- **The user is about to onboard someone, write a README, open a PR, or create a design doc**:
  these are exactly the contexts where a diagram becomes living, version-controlled
  documentation instead of a one-off explanation that goes stale.
- **A plan or architecture is being discussed before implementation**: sketching the diagram
  first, before writing code, catches structural problems earlier and cheaper than catching
  them in code review.

## When not to bother

- The structure being explained is genuinely linear and simple enough that a diagram would
  add ceremony without adding clarity (three steps in a strict sequence with no branches,
  for example).
- The user is asking a narrow, single-fact question where a diagram would be a non-sequitur.
- A diagram was already produced for the same structure earlier in the conversation and
  nothing about that structure has changed, don't regenerate it just to re-illustrate the
  same answer.

## Offer, don't just declare

When triggering unprompted, it's fine to just produce the diagram directly if the request is
clearly asking for an explanation of something diagrammable. If it's more ambiguous whether a
diagram is wanted alongside the prose answer, a brief diagram can still accompany the
explanation rather than being asked about first, prose plus diagram is rarely worse than prose
alone when the underlying structure genuinely has entities and relationships.

## This is not the same as an inline chat visual

If the environment has a separate, general-purpose visualization tool for one-off inline
diagrams shown directly in a chat interface, that tool and this skill can overlap in
capability but serve different purposes: this skill is for diagrams meant to be saved,
committed, and rendered by GitHub, GitLab, Notion, or a documentation site, meaning valid
Mermaid syntax that will keep working wherever it's embedded. When the target is specifically
a repo file, a PR description, a README, or any other place Mermaid syntax will be read
directly rather than rendered once and discarded, this skill's output format (plain Mermaid
in a fenced code block or a `.mmd` file) is the right one to use.
