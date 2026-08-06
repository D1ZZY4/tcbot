---
name: context7-expert
description: >
  Fetch current, version-accurate documentation for any library, framework, SDK, API, CLI
  tool, or cloud service via Context7, instead of answering from training data that may be
  outdated. Use proactively and silently, not only when the user says "context7" or "use
  context7". Trigger for setup, config, API signature, or "how do I" questions naming a
  library, before writing or fixing code that calls a specific library's API without full
  certainty it's current, whenever a version is mentioned, and whenever confidence is anything
  less than certain. Applies even to well-known libraries (React, Next.js, Prisma, Express,
  Tailwind, Django, Spring Boot) since APIs drift between versions. Not for refactoring,
  from-scratch scripts with no library involved, business logic debugging, general code
  review, or library-independent programming concepts.
---

# Context7 Expert

This file is the workflow index. Details live in `references/`, load the specific file for
the mode or step you're on rather than guessing.

## Step 0: Trigger proactively, and pick the right mode silently

Don't wait for the word "context7" to be typed, and don't narrate that you're about to use it,
just do it. Read `references/proactive-trigger.md` for the full trigger conditions and the
confidence threshold for when training data is good enough on its own.

Before doing anything else, check what's actually available in this environment:

- **MCP tools present** (a Context7 MCP server is connected, tools with names like
  `resolve-library-id` and `get-library-docs` or `query-docs` appear in the tool list): use
  MCP mode. Read `references/mcp-mode.md`.
- **No MCP tools, but a shell/bash tool and an installed `ctx7` CLI are available**: use CLI
  mode. Read `references/cli-mode.md`.
- **No MCP tools and no installed CLI**: ask before using the transient `npx` fallback unless
  network-backed package execution was already explicitly approved for this request. Do not
  install globally or change project configuration just to answer a documentation question.
- **Neither is available**: say so plainly, answer from training knowledge, and flag that the
  answer may be outdated for fast-moving libraries. Never silently pretend training data is
  current.

Don't ask the user which mode to use, detect it from what's actually available and proceed.

## Step 1: Resolve the library

Both modes are a two-step process: resolve the library name to an exact ID first, then fetch
docs with that ID. Read `references/selection-and-query-writing.md` for the shared selection
criteria (name match, description relevance, code snippet count, source reputation, benchmark
score) and query-writing rules that apply to both modes. Skip the resolve step only when the
user already gave an exact ID in `/org/project` or `/org/project/version` format.

## Step 2: Fetch and use the documentation

Query using the resolved ID, one concept per query, never combine unrelated topics into one
call (see `references/selection-and-query-writing.md` for why and for good/bad query
examples). Use the returned docs to answer, including relevant code examples, and mention the
library version when it's relevant to the answer.

Read `references/risk-and-budget.md` before choosing the operation budget. Use three operations
as the default for a normal question, but allow a documented increase when the user explicitly
asks about multiple libraries, a migration, security-sensitive behavior, or a version-specific
breaking change. Every retry and fetch still counts, and the budget must remain finite.

## Step 3: Handle failures honestly

If a call fails, returns nothing useful, or a quota/rate limit is hit, don't silently fall
back to training data. Tell the user what happened and that the answer that follows (if any)
is from training knowledge and may be outdated. See the error-handling section in
`references/mcp-mode.md` or `references/cli-mode.md` for mode-specific detail.

## Bonus: managing skills and setup via the CLI

The `ctx7` CLI does more than fetch docs, it can also install, search, and generate other
skills, and configure Context7 MCP for an editor. These aren't triggered by documentation
questions, only by explicit requests to manage skills or set up Context7 itself. Read
`references/cli-skills-management.md` and `references/setup.md` when that's what's being
asked for.

## Anti-patterns to reject

- Answering an API/config/setup question about a specific library from training data alone
  when Context7 (MCP or CLI) is available and wasn't tried
- Narrating "let me use Context7" or similar before every call, just do it
- Combining multiple distinct concepts into one query instead of splitting per concept
- Retrying beyond the finite risk-tier budget instead of using the best result available
- Silently falling back to training data on a tool failure or quota error without telling the
  user
- Using this skill for refactoring, from-scratch scripts with no library involved, business
  logic debugging, or general code review, none of that is documentation lookup

## Bundled references

- `references/proactive-trigger.md`: full trigger conditions and confidence threshold.
- `references/mcp-mode.md`: full detail for MCP mode, tool names, selection, error handling.
- `references/cli-mode.md`: full detail for CLI mode, commands, auth, error handling.
- `references/selection-and-query-writing.md`: shared library selection and query rules.
- `references/risk-and-budget.md`: risk tiers and adaptive operation budgets.
- `references/cli-skills-management.md`: install/search/suggest/generate skills via `ctx7`.
- `references/setup.md`: configuring Context7 MCP or CLI + Skills mode for an editor.
- `references/agent-adapters.md`: optional target-agent setup and installation locations.
