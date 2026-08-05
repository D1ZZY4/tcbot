# Skills Management via ctx7

Not triggered by documentation questions, only when the user explicitly asks to install,
search, suggest, list, remove, or generate AI coding skills through the `ctx7` CLI. Skills here
are Markdown files that teach AI coding agents best practices, patterns, and workflows for a
specific library or task, the same shape as this skill itself.

## Install

Repository format is always `/owner/repo`.

```bash
npx ctx7@latest skills install /anthropics/skills           # interactive, pick from a list
npx ctx7@latest skills install /anthropics/skills pdf        # install a specific skill by name
npx ctx7@latest skills install /anthropics/skills --all      # install everything, no prompts
```

Target a specific agent with a flag, otherwise the CLI prompts interactively:

```bash
npx ctx7@latest skills install /anthropics/skills pdf --claude     # Claude Code only
npx ctx7@latest skills install /anthropics/skills pdf --cursor     # Cursor only
npx ctx7@latest skills install /anthropics/skills pdf --universal  # universal (.agents/skills/)
npx ctx7@latest skills install /anthropics/skills --all --global   # all skills, global install
```

Alias: `ctx7 si /anthropics/skills pdf`

## Search

```bash
npx ctx7@latest skills search pdf
npx ctx7@latest skills search typescript testing
```

Alias: `ctx7 ss pdf`

## Suggest

Auto-detects the current project's dependencies (reads `package.json`,
`requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`) and recommends
relevant skills from the registry. Falls back to suggesting a manual `skills search` if no
dependencies are detected.

```bash
npx ctx7@latest skills suggest           # scan current project, install to project
npx ctx7@latest skills suggest --global  # install suggestions globally
```

Alias: `ctx7 ssg`

## Generate (AI-powered, requires login)

```bash
npx ctx7@latest skills generate
npx ctx7@latest skills generate --claude   # install directly to Claude Code
```

Interactive flow: describe the expertise wanted, select relevant libraries from search
results, answer a few clarifying questions, review the generated skill, choose where to
install it. Free accounts get a limited number of generations per week, paid accounts get
more, check current limits with the CLI itself since these change.

Aliases: `ctx7 skills gen`, `ctx7 skills g`

## List, remove, info

```bash
npx ctx7@latest skills list                   # current project, all detected agents
npx ctx7@latest skills list --global --claude # global Claude Code skills only

npx ctx7@latest skills remove pdf             # uninstall by name
npx ctx7@latest skills remove pdf --claude    # from Claude Code only

npx ctx7@latest skills info /anthropics/skills  # preview a repo's skills without installing
```

Aliases for remove: `ctx7 skills rm`, `ctx7 skills delete`

## Agent target flags

| Flag | Directory | Used by |
|------|-----------|---------|
| `--universal` | `.agents/skills/` | Amp, Codex, Gemini CLI, OpenCode, GitHub Copilot |
| `--claude` | `.claude/skills/` | Claude Code |
| `--cursor` | `.cursor/skills/` | Cursor |
| `--antigravity` | `.agent/skills/` | Antigravity |

Add `--global` to any flag to install in the home directory instead of the current project.
Without a flag, the CLI prompts interactively for one or more targets.
