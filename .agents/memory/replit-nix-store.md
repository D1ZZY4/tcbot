---
name: Replit nix store constraint
description: uv sync fails writing to nix store; fix is to create local .venv and set UV_PROJECT_ENVIRONMENT=.venv
---

# Replit Nix Store: Constraint (Active)

## The rule

`uv sync` and `uv run` fail on this Replit environment because the nix python store is read-only.

**Error:**
```
Failed to install: <package>
  Caused by: failed to create directory `/nix/store/.../site-packages/<pkg>`: Permission denied (os error 13)
```

**Why:** The nix store (`/nix/store/...python3.../site-packages/`) is read-only. `uv run` attempts `uv sync` before running, which triggers this error.

**Fix (one-time setup):**
```bash
uv venv .venv
UV_PROJECT_ENVIRONMENT=.venv uv sync
```

**Workflow command:**
```
UV_PROJECT_ENVIRONMENT=.venv uv run python -m tcbot
```

**How to apply:**
- Always prefix `uv run` with `UV_PROJECT_ENVIRONMENT=.venv` in workflow commands and manual runs.
- The `.venv` directory is writable and lives in the project root.
- If `.venv` is missing (e.g. after a fresh clone), run `uv venv .venv && UV_PROJECT_ENVIRONMENT=.venv uv sync` first.
- Do NOT use raw `python -m tcbot` without `uv run` — it won't have the correct sys.path.
- Workflow output type must be `console` (not `webview`) since the bot is a Telegram polling bot, not a web app exposed on port 5000.
