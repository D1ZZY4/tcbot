# Skills Management via ctx7

Not triggered by documentation questions, only when the user explicitly asks to install,
search, suggest, list, remove, or generate AI coding skills through the `ctx7` CLI. Skills here
are Markdown files that teach AI coding agents best practices, patterns, and workflows for a
specific library or task, the same shape as this skill itself.

All commands in this reference are mutating operations. Confirm the requested target and scope
before running them. Never add `--all`, `--global`, or a removal command based only on a
dependency scan or a proactive suggestion.

## Install

Repository format is always `/owner/repo`.

```bash
npx ctx7@latest skills install /owner/repository             # interactive, pick from a list
npx ctx7@latest skills install /owner/repository skill-name  # install a specific skill
npx ctx7@latest skills install /owner/repository --all       # install everything, no prompts
```

Target a specific agent only through a currently supported host adapter, otherwise let the CLI
prompt interactively. Treat the target flag and install directory as adapter details, not a
universal skill location. Read `agent-adapters.md` before selecting one. Do not copy a flag from
another host into a different agent's command:

```bash
npx ctx7@latest skills install /owner/repository skill-name <host-adapter-flags>
```

Alias: `ctx7 si /owner/repository skill-name`

## Search

```bash
npx ctx7@latest skills search pdf
npx ctx7@latest skills search typescript testing
```

Alias: `ctx7 ss pdf`

## Suggest

Auto-detects the current project's dependencies (reads `package.json`, `requirements.txt`,
`pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`) and recommends relevant skills from the
registry. Falls back to suggesting a manual `skills search` if no dependencies are detected.

```bash
npx ctx7@latest skills suggest           # scan current project, install to project
npx ctx7@latest skills suggest --global  # install suggestions globally
```

Alias: `ctx7 ssg`

## Generate (AI-powered, requires login)

```bash
npx ctx7@latest skills generate
npx ctx7@latest skills generate <host-adapter-flags>
```

Interactive flow: describe the expertise wanted, select relevant libraries from search
results, answer a few clarifying questions, review the generated skill, choose where to
install it. Free accounts get a limited number of generations per week, paid accounts get
more, check current limits with the CLI itself since these change.

Aliases: `ctx7 skills gen`, `ctx7 skills g`

## List, remove, info

```bash
npx ctx7@latest skills list                   # current project, all detected agents
npx ctx7@latest skills list <host-adapter-flags>

npx ctx7@latest skills remove pdf             # uninstall by name
npx ctx7@latest skills remove skill-name <host-adapter-flags>

npx ctx7@latest skills info /owner/repository  # preview a repo's skills without installing
```

Aliases for remove: `ctx7 skills rm`, `ctx7 skills delete`

Add `--global` to any flag to install in the home directory instead of the current project.
Without a flag, the CLI prompts interactively for one or more targets.
