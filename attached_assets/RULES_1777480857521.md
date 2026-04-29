# Rules for AI Agents

This project is a pure Python Telegram bot for Transsion Core Federation (TCF). Strictly follow these rules:

1.  **No emoji** in any message, caption, button text, or file content.
2.  **Python 3.11+** must be used. The bot runs via `python -m tgbot_tcf`.
3.  **python-telegram-bot v22.5** – asynchronous, `Application.builder()`, `ConversationHandler`.
4.  **MongoDB** via `motor` async driver. Database name: `tcf_bot`. Credentials MUST be stored in a `.env` file (never hardcoded) and loaded with `python-dotenv`. Provide an **example environment file** named `c.env.example` (the user will copy it to `.env` for actual use) with placeholder keys `BOT_TOKEN` and `MONGODB_URI`.
5.  **Environment variables** must be loaded from the system – never hardcoded. Use `os.getenv` or `dotenv.load_dotenv()`.
6.  **Project structure** – the following exact layout MUST be used. Do NOT deviate:
    ```
    tgbot_tcf/
      modules/        # optional, for feature-specific extra logic if needed
      handlers/       # core telegram update handlers (commands, conversations, callbacks)
        helper/       # shared handler helpers (e.g., target resolution, auth checks)
      utils/          # generic utilities (logging setup, HTML formatting, link builders)
      database/       # MongoDB connection and all collection access functions
      __main__.py     # entry point: load env, connect DB, build Application, start Flask, run polling
      __init__.py     # package marker
      c.env.example   # example env file (contains BOT_TOKEN, MONGODB_URI placeholders)
      keepalive.py    # Flask app for keep‑alive server
    ```
7.  **No web-related files** except the minimal Flask keep‑alive server (port 8080) in `keepalive.py`. Do **not** create `package.json`, `pnpm-lock.yaml`, Node.js files, or any other web framework beyond that Flask server.
8.  **Follow the full specification** in `PROMPT.md` exactly – every feature, alias, log format, inline keyboard layout, and behaviour described there must be implemented.
9.  **Always generate a `README.md`** that explains:
    - What the bot is
    - How to set up (clone, install dependencies, set env vars)
    - How to run (`python -m tgbot_tcf`)
    - The main features
    - The project structure (briefly)
    - Important notes (no emoji, credentials, etc.)
10. **Inline keyboards** must follow the layout rules in Feature 26 of `PROMPT.md` (2 buttons per row where possible, related actions in one row).
11. **Message editing** must be preferred over sending new messages.
12. **Error handling** – never let the bot crash; log errors with Python's `logging` module.
13. **All time formatting** must use UTC and format `DD-MM-YYYY | HH:MM`.
14. **All log messages** sent to the log channel must contain the exact branding line:
    `𝘛𝘊𝘍 - 𝘛𝘳𝘢𝘯𝘴𝘴𝘪𝘰𝘯 𝘊𝘰𝘳𝘦 𝘍𝘦𝘥𝘦𝘳𝘢𝘵𝘪𝘰𝘯`
15. **File size limit** – no single Python file shall exceed **600 lines** of code. If a module becomes too large, split it into smaller sub-modules within the same package. Keep the codebase maintainable and readable.
16. **Code quality** – use clear variable/function names, add docstrings for public functions, and keep cyclomatic complexity low. Follow PEP 8 style guidelines.
17. **Copyright notice** – add the following exactly as a comment at the top of every Python file (including `__init__.py`, `__main__.py`, `keepalive.py`, and all module files):
    ```python
    # © Copyright 2024 - 2026 Transsion Core
    # © Copyright 2024 - 2026 Dizzy
    # © Copyright 2026 Aveum Apps
    ```
    If the file already contains a shebang or encoding declaration, place the copyright block immediately below it.
18. **Comments and docstrings** – write clean, professional, and friendly comments. Explain "why" rather than "what" where appropriate. Keep the tone neutral but helpful, as a senior developer would. No slang, no emoji, no unnecessary commentary.
19. **Requirements file** – even if a `pyproject.toml` and `uv.lock` are present, you MUST provide a `requirements.txt` with exact versions for universal compatibility (Replit, Docker, CI). You can generate it from the `pyproject.toml` using `uv export --format requirements-txt` or write it manually. At minimum it must include:
    ```
    python-telegram-bot[job-queue]==22.5
    motor>=3.7.1
    flask>=3.1.3
    python-dotenv
    ```
    Pin the versions to match those locked in `uv.lock`.
20. **Additional configuration files** – always generate a `.replit` file with the following content:
    ```
    run = "python -m tgbot_tcf"
    language = "python3"
    ```
    This ensures the bot can be run directly on Replit.
21. **`.gitignore` file** – always generate a `.gitignore` suitable for a Python project. It must include at least:
    ```
    # Byte-compiled / optimized / DLL files
    __pycache__/
    *.py[cod]

    # Environment variables (real credentials)
    .env

    # Virtual environment
    venv/
    .venv/

    # IDE
    .vscode/
    .idea/

    # OS
    .DS_Store
    Thumbs.db
    ```
22. **Deliverable** – provide the full source code according to these rules and `PROMPT.md`, ready to deploy after setting the `.env` file.
23. **Cross‑platform compatibility** – the bot must be runnable on Linux, macOS, Windows, and Android (e.g. Termux) without modification. Do **not** create platform‑specific files like `Dockerfile`, `docker-compose.yml`, or any container configuration unless the user explicitly asks for a Docker deployment. The project should remain a simple Python package that works anywhere Python 3.11+ is available.
24. **Language tone** – all documentation, comments, and bot messages must use a friendly yet formal tone. Avoid slang, stiff professionalism, or any usage that sounds unnatural. The goal is clear, warm, and respectful communication without being casual.
25. **Pre‑existing deployment files** – the repository already contains a `Dockerfile`, `docker-compose.yml`, and `.github/workflows/run-bot.yml` provided by the user. Do **not** generate or modify these files. The project remains cross‑platform and can be run directly with Python on any OS.