# Agent Adapters

The Context7 workflow is agent-neutral. MCP and CLI are capabilities; the host agent's config
file and skill directory are adapter details.

## Generic adapter contract

Before setup or installation, identify:

1. the target agent,
2. the target scope, project-local or user-global,
3. the config or skill directory that agent documents,
4. whether the operation will modify files, install packages, or authenticate.

Require explicit approval for each mutating operation. Do not infer a target from the current
working directory alone.

## Known examples

Some agents expose target flags or conventional locations, such as:

- Some agents document project-local skill directories.
- Some agents document user-global skill directories.
- Some agents expose MCP configuration instead of a skill directory.

These are examples, not a universal contract. Read the target agent's current documentation
before writing configuration. Never assume that one host's discovery path works in another.

When a CLI supports target flags, keep those flags here with the matching host and CLI version.
The core workflow should use placeholders such as `<host-adapter-flags>`, never a flag copied
from one agent into instructions for all agents.

## Portability rule

Keep the Context7 lookup workflow in this skill. Keep host-specific commands, paths, and config
formats in the adapter documentation for the target agent. If no adapter is known, explain what
capability is missing instead of writing guessed configuration.
