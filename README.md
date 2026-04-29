# Transsion Core Federation (TCF) Telegram Bot

Production Telegram bot that manages the Transsion Core Federation: group affiliation, federation-wide bans with proof uploads, an admin hierarchy, an appeal flow, broadcast, ban sync, welcome / goodbye messages, and detailed channel logging.

## What it does

- Affiliates Telegram groups with TCF when added by the group owner.
- Lets Federation owners and admins issue federation-wide bans backed by proof (photos / videos / albums) posted to a dedicated proof topic.
- Provides an appeal flow over a deep-link, with admin Approve / Reject buttons in a dedicated review topic and a 12-hour exclusivity window for the original banning admin.
- Broadcasts plain-text announcements to every active affiliated group.
- Force-syncs bans across all affiliated groups when needed.
- Sends welcome and goodbye messages in the federation main group and exec group.
- Maintains an audit log of every federation event in a dedicated log channel, every entry stamped with the TCF branding line and a UTC timestamp formatted `DD-MM-YYYY | HH:MM`.
- Exposes an interactive start menu and an interactive help system in the bot's private chat.

## Setup

```bash
git clone <repo>
cd <repo>

# Python 3.11+
python -m venv .venv
source .venv/bin/activate
pip install -e .   # or: pip install python-telegram-bot[job-queue]==22.5 motor flask
```

Set the required environment variables:

| Variable        | Description                                  |
| --------------- | -------------------------------------------- |
| `BOT_TOKEN`     | Telegram bot token from @BotFather           |
| `MONGODB_URI`   | MongoDB connection string                    |
| `KEEPALIVE_PORT`| Optional. Port for the Flask keep-alive (default `8080`) |

## Running

```bash
python -m tgbot_tcf
```

The process starts a tiny Flask keep-alive server in a daemon thread (so platforms like Replit do not idle the bot) and then begins long-polling Telegram with `Application.builder()` from `python-telegram-bot` 22.5. MongoDB indexes are created automatically on startup, and the initial Federation Owner is seeded into the empty `fed_owners` collection.

On Replit, the supplied workflow `TCF Bot` runs the same command. Deployment is configured as a Reserved VM, suitable for an always-on polling bot.

## Command prefixes and aliases

Every command works with three prefixes and at least three aliases:

- Prefixes: `/`, `.`, `!` (e.g. `/cban`, `.cban`, `!cban` are equivalent).
- Aliases: e.g. `/cban`, `/comban`, `/fban`.

## Main features

1. Group affiliation on add, with Join / Cancel inline buttons (group owner only).
2. `/joinfed`, `/requestjoin`, `/applyfed` for explicit later affiliation.
3. `/defed`, `/leavefed`, `/unfed` and `/rmfed`, `/removefed`, `/deletefed` for disaffiliation.
4. `/cpromote`, `/cdemote`, `/transferowner` for the admin hierarchy (owner-only).
5. `/cban` with a 60-second proof collector (single media or album).
6. `/cunban` to lift a federation ban.
7. `/checkme` for a banned user to surface their record and an appeal deep-link.
8. Appeal system: `/start appeal_<ban_id>` → `#appeal` submission → admin Approve / Reject (12-hour rule).
9. `/baninfo`, `/checkban`, `/banstatus` to inspect any user's ban record.
10. `/fedgroups`, `/fedstats` read-only listings.
11. `/fedlinks`, `/links`, `/fedconfig` — official TCF links with URL buttons.
12. `/broadcast`, `/announce`, `/fcast` to all active groups.
13. `/syncban`, `/forcesync`, `/fbanall` to re-enforce a ban across every group.
14. `/leaveall`, `/exitall`, `/fedleave` and `/cleanup`, `/purge`, `/fedclean` maintenance.
15. About TCF reached only via the deep link `https://t.me/<bot>?start=about` and the start menu.
16. Interactive start menu (Row 1: About / Help, Row 2: Statistics / Federation Groups, Row 3: Federation Links).
17. Interactive `/help` and `/commands`: 7 rows × 2 buttons (Ban / Unban, Check Ban / Ban Info, Promote/Demote / Transfer Owner, Broadcast / Sync Ban, Group Affiliation / Disaffiliate, Appeal / Join/Leave, Statistics / Cleanup) with consistent Back navigation.
18. Welcome / goodbye messages in the federation main group and exec group.

## Project structure

```
tgbot_tcf/
├── __main__.py          # entry point: builds the Application and registers handlers
├── config.py            # constants, env loading, branding, hardcoded chat / topic IDs
├── keepalive.py         # tiny Flask app on port 8080 in a daemon thread
├── db/
│   └── mongo.py         # motor client + collections + index init
├── utils/
│   ├── auth.py          # is_fed_owner / is_fed_admin / is_authorized helpers
│   ├── format.py        # UTC time formatting, HTML link builders, topic links
│   ├── logger.py        # log_to_channel helper (HTML, optional inline keyboard)
│   ├── prefix.py        # multi-prefix dispatcher for `.cmd` and `!cmd`
│   └── targets.py       # reply / @username / numeric-id target resolver
└── handlers/
    ├── affiliate.py     # group affiliation, /joinfed, /defed, /rmfed, my_chat_member
    ├── admins.py        # /cpromote, /cdemote, /transferowner
    ├── ban.py           # /cban (with proof state machine) and /cunban
    ├── appeal.py        # deep-link appeal flow + admin Approve / Reject
    ├── broadcast.py     # /broadcast
    ├── sync.py          # /syncban
    ├── checks.py        # /checkme, /baninfo
    ├── lists.py         # /fedgroups, /fedstats
    ├── links.py         # /fedlinks
    ├── menu.py          # interactive start menu + interactive /help system
    ├── welcome.py       # welcome / goodbye in MAIN_GROUP and EXEC_GROUP
    ├── help.py          # /start, /help, /commands entry points
    └── maintenance.py   # /leaveall, /cleanup
```

## Important notes

- No emoji anywhere in messages, captions, or button labels.
- Credentials (`BOT_TOKEN`, `MONGODB_URI`) are loaded from the environment, never hardcoded.
- All UTC timestamps are formatted `DD-MM-YYYY | HH:MM`.
- Every log message sent to the log channel contains the branding line:

  `𝘛𝘊𝘍 - 𝘛𝘳𝘢𝘯𝘴𝘴𝘪𝘰𝘯 𝘊𝘰𝘳𝘦 𝘍𝘦𝘥𝘦𝘳𝘢𝘵𝘪𝘰𝘯`

- Hardcoded Telegram IDs live in `tgbot_tcf/config.py` (`LOG_CHANNEL`, `MAIN_GROUP`, `PROOF_TOPIC`, `APPEAL_TOPIC`, `APPEAL_DISCUSSION_TOPIC`, `MAIN_CHANNEL`, `EXEC_GROUP`, `INITIAL_OWNER_ID`).
- The keep-alive Flask server runs on port `8080` (overridable with `KEEPALIVE_PORT`).
