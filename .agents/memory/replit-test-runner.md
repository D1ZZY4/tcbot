---
name: Replit test runner
description: How to run tests and ruff in the Replit environment for TCF Bot; the normal uv commands fail due to nix Python permission issues.
---

## Problem

`uv sync --extra test` fails on Replit NixOS: uv tries to install into the read-only nix store Python at `/nix/store/...python3-3.12.12/lib/python3.12/site-packages/` and gets `Permission denied`.

`python3 -m pytest` resolves to `.pythonlibs/bin/python3` (Python 3.12) but the project packages are installed for Python 3.11 in `.pythonlibs/lib/python3.11/site-packages/`.

## Solution

Run tests using Python 3.11 with an explicit PYTHONPATH:

```bash
PYTHONPATH=/home/runner/workspace/.pythonlibs/lib/python3.11/site-packages python3.11 -m pytest tests/ -q
```

Run ruff using uvx (downloads and caches ruff in an isolated environment):

```bash
uvx ruff check .
uvx ruff format .
```

## Why

- `.pythonlibs/lib/python3.11/site-packages/` contains: `telegram`, `motor`, `dotenv`, `flask`, `pytest`, `pytest_asyncio`, and all other project dependencies.
- `.pythonlibs/bin/python3.11` is available and uses the correct site-packages via PYTHONPATH.
- `uvx ruff` works because uv can download and run ruff as a one-shot tool without installing into the project venv.

## Baseline (2026-06-02)

- 176 tests across 18 test files: all pass, zero warnings.
- `uvx ruff check .` → `All checks passed!`
