---
name: runtime-debugger
description: Diagnose project startup, polling, Telegram token, MongoDB, Flask keep-alive, handler registration, environment loading, and local runtime problems safely.
---
Last updated: 2026-05-28


# Runtime Debugger

Use this skill when the user asks to run the project, debug startup, inspect runtime logs, or diagnose local deployment problems.

## What This Skill Covers

- `python -m tcbot` startup failures
- invalid or missing `BOT_TOKEN`
- MongoDB connection or index setup issues
- Flask keep-alive binding problems
- handler registration/import errors
- environment loading from `config.env`
- Windows vs Linux command differences
- safe log interpretation without leaking secrets

## Safety Rules

- Do not print raw `BOT_TOKEN`, `MONGODB_URI`, passwords, or API keys.
- If the user says secrets can be shown, still prefer masked output unless raw values are absolutely required.
- Do not edit `config.env` unless the user explicitly asks.
- If checking config, report key presence, length, shape, and masked values.
- Use short timeouts when running the bot because polling is long-running.

## Useful Commands

Install runtime dependencies:

```bash
uv sync
```

Install test dependencies too:

```bash
uv sync --extra test
```

Start the bot through uv:

```bash
uv run python -m tcbot
```

Start from the virtual environment on Windows:

```bash
.venv/Scripts/python.exe -m tcbot
```

Start from an activated environment:

```bash
python -m tcbot
```

Run with a timeout from an agent tool so polling does not block forever.

## Startup Log Checklist

A healthy startup should reach lines similar to:

```text
Starting ... bot...
Keep-alive server started on 0.0.0.0:PORT
Handlers registered. Starting polling...
MongoDB connected → DB_NAME
MongoDB indexes ensured.
Bot initialised. Owner: ...
Scheduler started
```

Interpret common failures:

| Log/Error | Likely cause | Next check |
|---|---|---|
| `InvalidToken` / token `xx` | `BOT_TOKEN` placeholder or revoked token | Check `config.env` active `BOT_TOKEN` line, masked. |
| `BOT_TOKEN is required` | env var missing | Confirm `config.env` path and variable name. |
| MongoDB auth/network error | bad URI, IP allowlist, cluster down | Check masked `MONGODB_URI`, Atlas network access. |
| import error while loading module | syntax/import issue in module | Run Ruff/tests and inspect module loader logs. |
| address already in use | Flask port conflict | Change `PORT` or stop existing process. |

## Config Loading Checks

TCF Bot loads local config through `python-dotenv` from `config.env`. Useful non-secret checks:

- which `config.env` path was found,
- whether `BOT_TOKEN` exists,
- token length and whether it contains `:`,
- whether token equals placeholder `xx`,
- whether `MONGODB_URI` starts with `mongodb://` or `mongodb+srv://`, masked,
- required numeric IDs are parseable.

Example diagnostic style:

```text
config_path= C:\...\tgbot\config.env
BOT_TOKEN length=46 has_colon=True is_placeholder=False
MONGODB_URI scheme=mongodb+srv masked=mongodb+srv://...retryWrites=true
```

Do not paste real secrets into final output.

## Debugging Workflow

1. Reproduce with the user's preferred command when safe.
2. Identify the first real error after startup noise and warnings.
3. Separate harmless warnings from fatal errors.
4. Check config shape without leaking values.
5. If the issue is code-related, inspect the relevant module before editing.
6. Validate after changes with startup, Ruff, and focused tests when practical.

## Notes About Warnings

`PTBUserWarning` about `per_message=False` and `CallbackQueryHandler` can appear for ConversationHandlers. It is not automatically fatal. Treat it as informational unless the user is debugging callback tracking behavior.

## Final Response

Tell the user:

- whether startup reached polling,
- whether MongoDB connected,
- whether the bot kept running until timeout,
- the exact failing error if startup failed,
- the next fix in simple terms.
