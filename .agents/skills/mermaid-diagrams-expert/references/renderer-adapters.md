# Renderer and Platform Adapters

Mermaid syntax is portable, but renderer behavior is not. Keep target-platform behavior in this
adapter reference rather than treating one editor, documentation host, or CLI as universal.

## Identify the target

Before selecting syntax or validating a diagram, identify:

1. where the diagram will render,
2. which Mermaid renderer that target uses,
3. the renderer version or supported feature set,
4. whether optional layouts or icon packs are available.

Use the project's declared dependencies or renderer configuration when available. If the target
version is unknown, choose a broadly supported syntax or provide a fallback.

## Capability boundaries

- A local Mermaid package, browser import, CLI, and hosted Markdown renderer may use different
  versions or configuration.
- A diagram that renders locally is not automatically supported by the publication target.
- `architecture-beta` needs Mermaid v11.1.0 or newer in a renderer that implements it.
- Icon packs and ELK layout are optional capabilities. Detect them instead of assuming them.

Keep `@latest` in reference package-runner examples when the user explicitly approves a
temporary lookup or validation. Do not alter a project's dependency declaration merely to make
the example render.

## Confidentiality boundary

Do not send proprietary architecture, credentials, personal data, or private source code to an
online editor or hosted renderer. Prefer local validation for confidential material, or
anonymize labels and values before using a network service. Obtain approval before sending
diagram content outside the repository.