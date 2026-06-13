---
name: context7-mcp
description: Use this skill when writing code that calls any library API, configuring tools, debugging AttributeError/TypeError on library objects, or needing accurate method signatures. Activates for python-telegram-bot, motor, pymongo, ruff, pydantic, uv, and any other dependency in pyproject.toml. Use even when you think you know the answer -- training data may not reflect the installed version.
---

When writing code that touches any library in this project, use Context7 to
fetch current, version-accurate documentation instead of relying on training
data. This is mandatory, not optional.

## When to Use This Skill

Activate this skill when you need to:

- Write or review code that calls a library method or constructor
  ("How does `ApplicationBuilder` work in PTB 22.x?")
- Configure a tool via `pyproject.toml` or CLI
  ("What is the correct line-length key for ruff?")
- Debug a runtime error involving a library object
  (`AttributeError`, `TypeError`, `ImportError` on any external class)
- Verify async API behavior in Motor or python-telegram-bot
  ("Does `AsyncIOMotorCollection.find` return a cursor or a coroutine?")
- Handle a version migration or breaking change
  ("What changed in python-telegram-bot between 21.x and 22.x?")

Do NOT use for: refactoring business logic, writing scripts from scratch,
debugging custom TCF Bot logic unrelated to library APIs, code review, or
general Python concepts.

## How to Fetch Documentation

### Replit Agent: Use the ctx7 CLI (MANDATORY)

On Replit, MCP tools are not available in the agent sandbox. Use the `ctx7`
CLI instead. The `CONTEXT7_API_KEY` secret is already set in the environment.

**Step 1: Resolve the library ID:**

```bash
ctx7 library "python-telegram-bot" "your question here"
```

Pick the result with the highest Benchmark Score and closest name match.
Prefer version-specific IDs when available (e.g. a v22.x entry over generic).

**Step 2: Fetch the docs:**

```bash
ctx7 docs "/python-telegram-bot/python-telegram-bot" "your specific question"
```

Use the library ID from Step 1. Ask a specific question, not just keywords.

**Step 3: Apply and record:**

Use the fetched docs to write or fix code. If you find a significant
non-obvious API detail, record it in `.agents/memory/decisions.md`.

### Preferred Library IDs for This Project

| Library | Best Context7 ID | Benchmark |
|---|---|---|
| `python-telegram-bot` | `/python-telegram-bot/python-telegram-bot` | 86.8 |
| `python-telegram-bot` (alt, more snippets) | `/websites/python-telegram-bot_en_stable` | 71.3 |
| `motor` | `/mongodb/motor` | 85.86 |
| `pymongo` | resolve via `ctx7 library "pymongo" "..."` | N/A |
| `ruff` | resolve via `ctx7 library "ruff" "..."` | N/A |

### External AI Tools (Roo, Claude Desktop, Cursor)

These tools connect via MCP directly: config is in `.agents/mcp.json` and
`.roo/mcp.json`. No CLI needed for these agents.

## Selection Rules

From resolution results, choose based on:

- Exact or closest name match to the installed package
- Higher benchmark scores indicate better documentation quality
- If the installed version is specified in `uv.lock`, prefer version-specific
  IDs when available (e.g., a PTB 22.x-specific entry over a generic one)
- Prefer official/primary packages over community forks

If results do not look right, try alternate names (e.g., `"telegram"` instead
of `"python-telegram-bot"`, or `"pymongo"` for Motor internals) or rephrase
the query.

## Fallback When Context7 Has No Result

Read the installed source directly:

```bash
# Inspect a specific method
uv run python -c "import inspect, telegram; print(inspect.getsource(telegram.Bot.ban_chat_member))"

# List all attributes of a class
uv run python -c "import motor.motor_asyncio as m; print(dir(m.AsyncIOMotorCollection))"

# Check installed version
uv run python -c "import telegram; print(telegram.__version__)"
uv run python -c "import motor; print(motor.version)"
```

## Priority Libraries for This Project

Always verify via Context7 before writing code that uses these:

| Library | pyproject.toml name | Why |
|---|---|---|
| `python-telegram-bot` | `python-telegram-bot` | Frequent breaking changes between minor versions; handler registration, filter API, and Application lifecycle all shift |
| `motor` | `motor` | Async cursor API differs from sync pymongo; method names and return types are not identical |
| `pymongo` | `pymongo` | Index syntax, aggregation pipeline operators, and session API evolve across versions |
| `ruff` | `ruff` | Rule codes and `pyproject.toml` config keys change between releases |
| `pydantic` | `pydantic` | v1 and v2 APIs are completely different; validators, field types, and model config all changed |

## MCP Server Configuration (for external tools only)

Config lives in `.agents/mcp.json` and `.roo/mcp.json`. Uses `CONTEXT7_API_KEY`
from Replit Secrets (no hardcoded value needed).

```json
"mcpServers": {
  "context7": {
    "type": "http",
    "url": "https://mcp.context7.com/mcp",
    "headers": {
      "CONTEXT7_API_KEY": "${CONTEXT7_API_KEY}"
    }
  }
}
```

## Installation Notes (Replit)

The `ctx7` CLI is installed globally via `npm install -g ctx7`. Binary path:
`/home/runner/workspace/.config/npm/node_global/bin/ctx7`

The CLI auto-picks `CONTEXT7_API_KEY` from the environment (no prefix needed):

```bash
ctx7 library "python-telegram-bot" "your question"
ctx7 docs "/python-telegram-bot/python-telegram-bot" "your question"
```
