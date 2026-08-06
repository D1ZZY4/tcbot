# Setup

Not triggered by documentation questions, only when the user explicitly asks to set up or
configure Context7 for their editor or coding agent.

## ctx7 setup

One-time command that configures Context7 for an AI coding agent. On first run it prompts for
a mode:

- **MCP server**: registers the Context7 MCP server so the agent can call its tools natively.
  This is what makes `mcp-mode.md` applicable afterward.
- **CLI + Skills**: installs a `find-docs`-style skill that guides the agent to use `ctx7` CLI
  commands directly, no MCP server required. This is what makes `cli-mode.md` applicable.

These are reference commands only. Do not run setup, change agent configuration, install a
skill, or authenticate merely because a documentation task mentions Context7. Perform setup
only after the user explicitly requests it and confirms the target and mode. Do not use
`--yes` by default. The exact target flags and configuration locations are host-specific.
Read `agent-adapters.md` and the target agent's current documentation before running one.

```bash
npx ctx7@latest setup                     # interactive, prompts for mode then agent/target
npx ctx7@latest setup --mcp               # skip the prompt, use MCP server mode
npx ctx7@latest setup --cli               # skip the prompt, use CLI + Skills mode
npx ctx7@latest setup --project           # configure the current project instead of globally
```

## Authentication options

Authentication is also an explicit user action. Never put an API key in a shell command or
commit it to a file; use the workspace's secret flow when a key is required. Do not initiate
login, logout, OAuth, or credential changes during a normal documentation lookup.

Without `--api-key` or `--oauth`, setup opens a browser for OAuth login. MCP mode additionally
generates a new API key after login. `--oauth` only applies to MCP mode.

## What gets written

**MCP mode:**
- An MCP server entry in the target agent's documented config file
- A Context7 rule file instructing the agent to use Context7 for library docs
- A `context7-mcp`-style skill in the agent's skills directory

**CLI + Skills mode:**
- A `find-docs`-style skill in the chosen agent's skills directory, guiding it to use
  `ctx7 library` and `ctx7 docs` commands

## Which mode to recommend

If the user hasn't specified a preference, MCP mode is generally lower friction once set up,
since tools are called natively without shelling out. CLI + Skills mode is the better fit when
the environment doesn't support MCP servers, or when the user is working somewhere with tighter
constraints around what can be installed or configured (for example, a mobile terminal
environment where a persistent MCP server process isn't practical). Ask if genuinely unsure,
don't default silently to one over the other when the tradeoff actually matters for the setup.
