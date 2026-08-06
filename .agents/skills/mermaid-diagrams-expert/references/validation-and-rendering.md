# Validation, Rendering, and Export

Full detail for Step 3 in SKILL.md. The single biggest weakness in delivering hand-written
Mermaid syntax is that it's easy to produce something that looks plausible but fails to
render, or renders with a subtly wrong structure, and never notice.

## Validate before delivering, when possible

If a compatible Mermaid renderer is already available, render the diagram rather than trusting
the syntax on sight. First identify the renderer and version, then check that it supports the
diagram type and configuration being used:

```bash
mmdc -i diagram.mmd -o diagram.svg
```

Do not install packages, invoke a network-backed fallback, or start Docker merely to validate a
diagram. Ask for approval before setting up a renderer. If approval is given for a temporary
Mermaid CLI invocation, use the current package explicitly:

```bash
npx @mermaid-js/mermaid-cli@latest -i diagram.mmd -o diagram.svg
```

This is a reference command only. It must not run implicitly, and the target project must not be
changed just to validate a diagram.

A clean exit with an output file means the syntax parsed. An error output means something in
the diagram is invalid, fix it before presenting the diagram as finished rather than handing
over syntax that was never actually checked.

If no rendering tool is available in the environment, say so plainly rather than silently
skipping validation, the same honesty principle as any other tool-unavailable situation:
present the diagram, but note it hasn't been rendered. An online editor such as
[mermaid.live](https://mermaid.live) is a verification option for non-confidential diagrams;
obtain approval before sending private architecture, source code, personal data, or credentials
outside the repository. Verify the result before relying on it, especially for anything going
into a PR or shared doc.

## Common pitfalls

- **Unknown or misspelled keywords break the diagram.** `classDiagram` typo'd as
  `classDiagrm` doesn't degrade gracefully, it fails. Double check the diagram-type keyword
  against the relevant reference file.
- **Parameters fail silently, not loudly.** An unrecognized config option or theme variable is
  often just ignored rather than raising an error, so a diagram can render "successfully"
  while quietly not applying an intended style. If a theming option doesn't seem to be taking
  effect, check the option name against `advanced-features.md` rather than assuming it's a
  rendering issue.
- **Special characters need escaping or quoting.** Characters like `{`, `}`, `"`, and `:`
  inside labels can be misread as syntax rather than literal text. Wrap labels containing them
  in quotes: `A["Handles {retry} logic"]` rather than `A[Handles {retry} logic]`.
- **Line breaks inside labels use `<br/>`, not a literal newline**, a literal newline in the
  middle of a label definition usually breaks parsing rather than wrapping the text.
- **Reserved words as node IDs cause conflicts.** Avoid naming a flowchart node `end`, `class`,
  `state`, or other Mermaid keywords, even though it might look like a normal identifier.
- **Overcomplexity reads as a bug even when it isn't one.** A diagram that's technically valid
  but has too many crossing lines or too many entities is a design problem, not a syntax
  problem, see the splitting guidance in `diagram-type-selection.md`.
- **Missing relationships silently understate the model.** It's easy to add all the entities
  and forget a relationship between two of them, if reviewing a diagram against the actual
  code or schema it documents, check for connections that exist in reality but got left out.

## Export options

Only bring these up when the user actually needs an image file, not by default, most Mermaid
diagrams are consumed as rendered Markdown, not exported images.

- **[Mermaid Live Editor](https://mermaid.live)**: online editor with instant preview and
  PNG/SVG export, also the fastest way to manually sanity-check a diagram if no local
  rendering tool is available.
- **Mermaid CLI**: use an existing installation with `mmdc -i input.mmd -o output.png`
  (or `.svg`, `.pdf`). If a temporary setup is explicitly approved, use the current
  `@mermaid-js/mermaid-cli@latest` package runner shown above.
- **Docker**: a user-approved alternative when a local renderer is unavailable. Do not start
  Docker implicitly.

## Where diagrams may render without export

Many versions of GitHub, GitLab, Notion, Obsidian, and Confluence support fenced ` ```mermaid `
code blocks, while VS Code commonly relies on the "Markdown Preview Mermaid Support" extension.
Feature support varies by platform, renderer version, and configuration. Verify the target before
using advanced syntax. Default to embedding a Markdown code block when the target supports the
selected diagram type, and use image export only when the destination does not render compatible
Mermaid syntax, such as a slide deck, PDF report, or email.

## Confidentiality and renderer boundaries

Do not paste proprietary architecture, credentials, personal data, or private source code into
an online renderer or public diagram service. Prefer a local renderer for confidential material,
or anonymize labels and values before using a network service. Treat Mermaid Live and any
third-party renderer as an external data boundary and obtain approval before sending content
outside the repository.

The diagram authoring syntax is portable, but renderer behavior is not. Record the target
renderer, version, and any optional icon or layout packs when reproducibility matters.
