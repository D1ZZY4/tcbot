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

### Step 1: Resolve the Library ID

Call `resolve-library-id` with:

- `libraryName`: the library name as it appears in `pyproject.toml`
  (e.g., `"python-telegram-bot"`, `"motor"`, `"ruff"`)
- `query`: your specific question (improves relevance ranking)

### Step 2: Select the Best Match

From the resolution results, choose based on:

- Exact or closest name match to the installed package
- Higher benchmark scores indicate better documentation quality
- If the installed version is specified in `uv.lock`, prefer version-specific
  IDs when available (e.g., a PTB 22.x-specific entry over a generic one)
- Prefer official/primary packages over community forks

If results do not look right, try alternate names (e.g., `"telegram"` instead
of `"python-telegram-bot"`, or `"pymongo"` for Motor internals) or rephrase
the query.

### Step 3: Fetch the Documentation

Call `query-docs` with:

- `libraryId`: the selected Context7 library ID (format: `/org/project`)
- `query`: your specific question, not just single keywords

### Step 4: Apply the Documentation

Use the fetched documentation to write or fix the code:

- Verify method signatures against the installed version in `uv.lock`
- If the fetched docs describe a different version than what is installed,
  note the discrepancy and fall back to inspecting the installed source
- Record significant findings in `.agents/memory/decisions.md` so future
  sessions skip the lookup

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

## MCP Server Configuration

```json
"mcpServers": {
  "context7": {
    "type": "http",
    "url": "https://mcp.context7.com/mcp",
    "headers": {
      "CONTEXT7_API_KEY": "ctx7sk-402fb223-6ea3-4559-bfaa-8b55298ecd01"
    }
  }
}
```