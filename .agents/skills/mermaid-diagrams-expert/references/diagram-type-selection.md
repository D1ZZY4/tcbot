# Diagram Type Selection

Full detail for Step 1 in SKILL.md. Pick by what's actually being modeled, not by habit or by
whichever diagram type was used last.

## Decision guide

Ask what the core subject is:

**Is it about objects and their structure?** (classes, entities, what properties and methods
something has, how types relate through inheritance or composition)
→ Class diagram (`references/class-diagrams.md`)

**Is it about things happening over time, in order?** (a request hitting an API, a user
authenticating, one service calling another, retries, timeouts)
→ Sequence diagram (`references/sequence-diagrams.md`)

**Is it about a process with decisions or branches?** (a user journey, an algorithm, a CI/CD
pipeline, "if this then that")
→ Flowchart (`references/flowcharts.md`)

**Is it about data storage structure?** (database tables, foreign keys, which fields belong to
which table, one-to-many vs many-to-many)
→ ERD (`references/erd-diagrams.md`)

**Is it about how systems and services fit together, at a zoomed-out level?** (what talks to
what, external dependencies, container boundaries, without getting into class-level detail)
→ C4 diagram (`references/c4-diagrams.md`)

**Is it about physical or cloud infrastructure?** (servers, load balancers, regions, managed
services, deployment topology)
→ Architecture diagram (`references/architecture-diagrams.md`)

**Is it about one object's lifecycle?** (valid states and what transitions between them,
a resource's status field, an order's lifecycle)
→ State diagram (`references/misc-diagrams.md`)

**Is it about branching and merging in version control?** (a Git workflow, a release strategy)
→ Git graph (`references/misc-diagrams.md`)

**Is it about scheduling or a timeline?** (project phases, deadlines, dependencies between
tasks over calendar time)
→ Gantt chart (`references/misc-diagrams.md`)

**Is it about proportions or a simple category comparison?** (percentages, relative sizes,
counts across a few categories)
→ Pie or bar chart (`references/misc-diagrams.md`)

## When more than one type could technically work

Some structures could be shown more than one way, pick based on what the reader needs to walk
away understanding:

- A REST API's endpoints and how they're used over a request lifecycle: sequence diagram
  (the ordering and back-and-forth matters), not a flowchart (which would flatten the
  request/response pairing).
- A system's overall shape versus one specific interaction within it: C4 or architecture
  diagram for the overall shape, sequence diagram for the specific interaction. Don't try to
  cram both into one diagram.
- A domain model that also needs to show a typical usage sequence: two diagrams, a class
  diagram for the structure and a sequence diagram for the usage, not one diagram trying to be
  both.

## Splitting large diagrams

If a single diagram is accumulating more than roughly 10 to 15 entities or steps and getting
hard to read, that's the signal to split it, not to shrink the font or cram harder. Common
splits:

- By subsystem or bounded context, one diagram per major area, plus one high-level diagram
  showing how the areas connect.
- By zoom level, a C4 context diagram plus separate container diagrams for each system that
  needs more detail.
- By concern, a class diagram for structure plus a separate sequence diagram for behavior,
  rather than one diagram trying to show both.
