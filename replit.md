# Transsion Core Federation (TCF) Telegram Bot

Production Telegram bot that manages a federation of Telegram groups. It handles affiliation, centralized banning with proof uploads, an admin hierarchy, an appeal flow, broadcast, ban sync, an interactive help system, welcome / goodbye messages, and detailed channel logging.

## Stack

- Python 3.11
- python-telegram-bot 22.5 (async, polling) with JobQueue
- MongoDB via `motor` (database: `tcf_bot`)
- Flask for a small keep-alive server on port 8080

## Layout

```
tgbot_tcf/
├── __main__.py          # Entry point: builds the Application and registers handlers
├── config.py            # Constants, env loading, branding, hardcoded chat/topic IDs
├── keepalive.py         # Tiny Flask app on port 8080 (KEEPALIVE_PORT to override)
├── db/
│   └── mongo.py         # Motor client + collections + index init
├── utils/
│   ├── auth.py          # is_fed_owner / is_fed_admin / is_authorized helpers
│   ├── format.py        # UTC time formatting, HTML link builders, topic links
│   ├── logger.py        # log_to_channel helper (HTML, optional inline keyboard)
│   ├── prefix.py        # Multi-prefix dispatcher for `.cmd` and `!cmd`
│   └── targets.py       # Reply / @username / numeric-id target resolver
└── handlers/
    ├── affiliate.py     # Group affiliation, /joinfed, /defed, /rmfed, my_chat_member
    ├── admins.py        # /cpromote, /cdemote, /transferowner
    ├── ban.py           # /cban (with proof-collection state machine) and /cunban
    ├── appeal.py        # Deep-link appeal flow + admin Approve/Reject (12h rule)
    ├── broadcast.py     # /broadcast
    ├── sync.py          # /syncban
    ├── checks.py        # /checkme, /baninfo
    ├── lists.py         # /fedgroups, /fedstats
    ├── links.py         # /fedlinks (Federation Links with URL buttons)
    ├── menu.py          # /start menu and interactive /help system
    ├── welcome.py       # Welcome / goodbye in MAIN_GROUP and EXEC_GROUP
    ├── help.py          # /start, /help, /commands entry points
    └── maintenance.py   # /leaveall, /cleanup
```

## Required secrets

- `BOT_TOKEN` – Telegram bot token
- `MONGODB_URI` – MongoDB connection string

## Notes

- Every command works with three prefixes: `/cmd`, `.cmd`, and `!cmd`.
- Every command has at least three name aliases (e.g. `/cban`, `/comban`, `/fban`).
- All log messages sent to `LOG_CHANNEL` include the branded line `𝘛𝘊𝘍 - 𝘛𝘳𝘢𝘯𝘴𝘴𝘪𝘰𝘯 𝘊𝘰𝘳𝘦 𝘍𝘦𝘥𝘦𝘳𝘢𝘵𝘪𝘰𝘯`.
- Timestamps are UTC and formatted `DD-MM-YYYY | HH:MM`.
- The keep-alive Flask server runs on port **8080**.
- About the federation is reached only via the deep link `https://t.me/<bot>?start=about` and via the start menu (no `/about` command).
- Run locally with `python -m tgbot_tcf`. The `TCF Bot` workflow does this automatically.
- On startup the bot seeds the initial Federation Owner (`INITIAL_OWNER_ID` from `config.py`) into the empty `fed_owners` collection so commands are usable before the first group affiliation.

## Hardcoded Telegram IDs

See `tgbot_tcf/config.py`:

- `LOG_CHANNEL = -1003941141635`
- `MAIN_GROUP   = -1003872207988` (forum)
- `PROOF_TOPIC  = 67`
- `APPEAL_TOPIC = 12`
- `APPEAL_DISCUSSION_TOPIC = 11`
- `MAIN_CHANNEL = -1003852970764`
- `EXEC_GROUP   = -1002333013065`
- `INITIAL_OWNER_ID = 7146954165`
