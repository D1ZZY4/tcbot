# Replit Agent Instructions

This is a **Python only** project for the Transsion Core Federation (TCF) Telegram bot. Do not generate any of the following:

* `package.json`
* `pnpm-lock.yaml`
* Any `node_modules` or JavaScript/TypeScript files
* Any web framework other than the minimal Flask keep‑alive described below
* Any file that is not strictly required by `PROMPT.md` or `RULES.md`

## What you MUST generate

1.  All Python files needed for the Telegram bot as specified in `PROMPT.md`.
2.  The exact project structure defined in `RULES.md` (with `c.env.example` instead of `c.env`):
    ```
    tgbot_tcf/
      modules/
      handlers/
        helper/
      utils/
      database/
      __main__.py
      __init__.py
      c.env.example
      keepalive.py
    ```
3.  A `requirements.txt` file generated from the existing `pyproject.toml` (e.g., via `uv export --format requirements-txt`). It must contain the same dependencies as listed in `pyproject.toml` with versions from `uv.lock`.
4.  A `.replit` file containing:
    ```
    run = "python -m tgbot_tcf"
    language = "python3"
    ```
5.  A `c.env.example` file (example environment file) containing the placeholder keys:
    ```
    BOT_TOKEN=your_bot_token_here
    MONGODB_URI=your_mongodb_uri_here
    ```
6.  A `.gitignore` file (content as specified in `RULES.md`).
7.  A `keepalive.py` file with a minimal Flask app that listens on `0.0.0.0:8080`. The Flask server must be started in a daemon thread inside `__main__.py` before calling `run_polling()`. This is the **ONLY** web‑related code allowed.
8.  A `README.md` explaining the project, setup, and usage (follow `RULES.md` for content).

## Important rules

* Read and follow `RULES.md` at all times.
* Read and implement every detail in `PROMPT.md`.
* No emoji anywhere.
* Add the required copyright notice to every Python file (see `RULES.md`).
* No single Python file shall exceed 600 lines of code.
* Use a friendly yet formal tone in all documentation, comments, and messages. No alay, no slang, no stiff professionalism.
* Do not generate Docker or workflow files. They are already present in the repository.