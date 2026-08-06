---
name: mermaid-diagrams-expert
description: >
  Create professional software diagrams using Mermaid's text-based syntax: class diagrams,
  sequence diagrams, flowcharts, entity relationship diagrams, C4 architecture diagrams,
  state diagrams, git graphs, gantt charts, and pie/bar charts. Use proactively, not only
  when the user says "diagram" or "visualize". Trigger any time explaining a system's
  architecture, a database schema, an API or auth flow, a process or decision tree, a class
  or domain model, or a project timeline would genuinely be clearer as a diagram than as
  prose, and any time producing a persistent diagram for a README, PR, wiki, or design doc,
  when the target renderer supports the selected Mermaid version and diagram features, and
  stays version-controlled alongside the code it documents. Verify the actual target platform
  instead of assuming identical support everywhere. This is for diagrams that live in repos and
  docs, distinct from a one-off inline visual for the current conversation.
---

# Mermaid Diagrams Expert

This file is the workflow index. Details live in `references/`, load the specific file for
the diagram type or step you're on rather than guessing.

## Step 0: Trigger proactively

Read `references/proactive-trigger.md` for the full trigger conditions. Short version: don't
wait to be asked. If you're about to explain something that has real structure (entities and
relationships, a sequence of interactions over time, a decision tree, a system's components)
and prose would leave the reader reconstructing that structure in their head, offer or
produce a diagram instead of, or alongside, the explanation.

## Step 1: Pick the right diagram type

Read `references/diagram-type-selection.md` for the full decision guide. Short version:

| What you're modeling | Diagram type |
|---|---|
| Classes, domain objects, OOP structure | Class diagram |
| Interactions over time, API calls, message flows | Sequence diagram |
| Processes, decision trees, user journeys, algorithms | Flowchart |
| Database tables and their relationships | ERD |
| System architecture at context/container/component level | C4 diagram |
| Cloud infrastructure, deployment topology, CI/CD | Architecture diagram |
| An object's lifecycle and valid transitions | State diagram |
| Branching and merge strategy | Git graph |
| Project timeline and scheduling | Gantt chart |
| Proportions or simple category comparisons | Pie or bar chart |

State diagrams, git graphs, gantt charts, and pie/bar charts are all covered together in
`references/misc-diagrams.md`.

## Step 2: Write the diagram

All Mermaid diagrams open with a type declaration, then definition content:

```mermaid
diagramType
  definition content
```

- Start simple: core entities or steps first, add detail incrementally rather than trying to
  capture everything in one pass.
- Use meaningful names that match the actual code or schema, not placeholder labels, so the
  diagram stays useful as documentation rather than becoming stale illustration.
- Keep one diagram to one concept. If it's getting hard to read, split it into multiple
  focused diagrams rather than cramming more into one.
- Use `%%` for comments to explain non-obvious relationships.
- Load the specific reference file for the diagram type in use, syntax details (relationship
  types, arrow styles, block structures) live there, not duplicated here.

## Step 3: Validate before delivering

Read `references/validation-and-rendering.md` and `references/renderer-adapters.md` for the
full detail. Identify the target renderer and version before choosing syntax, then review the
diagram against the source model and render or lint it if an existing compatible tool is
available. Do not install packages or start Docker merely to validate a diagram unless the user
approves that setup. If rendering is unavailable, perform static syntax and structure review and
say that visual rendering was not verified.

## Step 4: Deliver appropriately

- Embed as a fenced ```` ```mermaid ```` code block in Markdown when it's going into a README,
  PR description, wiki page, or any doc that already renders Markdown.
- Save as a standalone `.mmd` file alongside the code it documents when the project's
  convention calls for that (check for an existing `docs/diagrams/` or similar folder first).
- Mention export options (Mermaid Live, `mmdc` CLI) only when the user needs an image file,
  not by default.

## Anti-patterns to reject

- Waiting for the word "diagram" before considering one, when the explanation being written
  clearly has diagrammable structure
- Delivering Mermaid syntax that was never rendered or checked, when a way to check it was
  available
- Cramming multiple unrelated concepts into one diagram instead of splitting into focused views
- Using placeholder or generic labels instead of the actual names from the code or schema
- Picking a diagram type by habit instead of by what's actually being modeled, see
  `references/diagram-type-selection.md`

## Bundled references

- `references/proactive-trigger.md`: full trigger conditions for reaching for a diagram
  unprompted.
- `references/diagram-type-selection.md`: full decision guide for picking a diagram type.
- `references/class-diagrams.md`: relationships, multiplicity, methods and properties.
- `references/sequence-diagrams.md`: actors, messages, activations, loops, alt/opt/par blocks.
- `references/flowcharts.md`: node shapes, connections, decision logic, subgraphs, styling.
- `references/erd-diagrams.md`: entities, relationships, cardinality, keys, attributes.
- `references/c4-diagrams.md`: system context, container, component diagrams, boundaries.
- `references/architecture-diagrams.md`: cloud services, infrastructure, CI/CD deployments.
- `references/misc-diagrams.md`: state diagrams, git graphs, gantt charts, pie/bar charts.
- `references/advanced-features.md`: themes, styling, configuration, layout options.
- `references/validation-and-rendering.md`: how to check a diagram before delivering it, plus
  export and rendering options.
- `references/renderer-adapters.md`: target-platform, renderer, version, and confidentiality
  boundaries.
