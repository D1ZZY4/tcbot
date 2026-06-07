---
name: Replit nix store constraint
description: uv sync fails on Replit because the nix-managed Python site-packages directory is read-only. Fix and runtime workaround.
---

# Replit Nix Store: Read-Only Constraint

## The rule

On Replit, the nix-managed Python interpreter at `/nix/store/.../python3.12/` has a read-only `site-packages` directory. `uv sync` (and `uv run`, which triggers sync) will fail with:

```
Failed to install: <package>.whl
Caused by: failed to create directory `/nix/store/.../lib/python3.12/site-packages/<pkg>`: Permission denied (os error 13)
```

This affects any package not already present in the nix store, including `ruff`, `flask`, `blinker`, and others.

**Why:** Replit's nix environment is immutable. The system Python is managed by Nix, not pip. `uv` tries to install into the active Python's site-packages, which is the nix store. Pip installs to `.pythonlibs/` instead (writable).

**How to apply:**

1. Install dependencies via `pip install ...` in Replit (packages land in `.pythonlibs/`).
2. Run commands directly: `python -m ruff check .`, `python -m tcbot`.
3. Never use `uv run` or `uv sync` in Replit workflows. Configure workflows to use `python ...` directly.
4. The `pyproject.toml` and `uv.lock` stay as-is for local/Docker development where `uv` works normally.
5. When new sessions start on Replit, re-run `pip install "python-telegram-bot[job-queue]==22.5" "motor>=3.7.1,<4" "flask>=3.1.0,<4" "python-dotenv>=1.0.0,<2" "ruff"` if packages are missing.
