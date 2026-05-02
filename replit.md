# TCF Telegram Bot

## Overview

A Telegram bot for the Transsion Core Federation (TCF) community. Manages federation-wide bans, appeals, group affiliations, admin promotions, and moderation.

## Architecture

- **Language:** Python 3.11
- **Bot framework:** python-telegram-bot 22.5 (polling mode)
- **Database:** MongoDB (via motor, async)
- **Web server:** Flask (keep-alive / health-check on port 5000)
- **Entry point:** `python3 -m tcbot`

## Key Modules

- `tcbot/config.py` — Centralised config object (`cfg`), loaded from `config.env`
- `tcbot/__init__.py` — Legacy `configs` singleton (kept for backward compat)
- `tcbot/__main__.py` — Entry point: sets up logging, starts Flask keepalive, discovers handlers, starts polling
- `tcbot/alive.py` — Flask keep-alive server running on port 5000
- `tcbot/database/` — MongoDB helpers (admins, bans, groups, users, warns, etc.)
- `tcbot/modules/` — Auto-discovered bot command modules (ban, appeal, connect, etc.)
- `tcbot/utils/` — Logging formatter, prefix builder, time utilities

## Configuration

All settings are in `config.env`. Key variables:

- `BOT_TOKEN` — Telegram bot token
- `OWNER_ID` — Initial owner Telegram user ID
- `MONGODB_URI` — MongoDB connection string
- `DB_NAME` — MongoDB database name
- `MAIN_GROUP` — Main Telegram group/forum chat ID
- `PORT` — Web server port (set to 5000 for Replit)

## Deployment

Deployment target: **vm** (always-running bot process)
Run command: `python3 -m tcbot`
