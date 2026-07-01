---
name: Replit nix store constraint
description: uv sync and uv run work correctly on this Replit environment (nix channel stable-25_05 with python-3.12 module).
---

# Replit Nix Store: Status

## The rule

`uv sync` and `uv run` work correctly on this Replit environment (nix channel `stable-25_05`, module `python-3.12`). The previous read-only nix store constraint no longer applies.

**Why:** As of the migration to Replit in June 2026, `uv sync` completed successfully and all packages were importable. `uv run python -m tcbot` starts the bot without errors.

**How to apply:**

- Use `uv run python -m tcbot` as the workflow command (already configured).
- Use `uv sync` to install/update dependencies.
- Do NOT switch to raw `pip install` or `python -m tcbot` directly: `uv run` handles the venv correctly.
