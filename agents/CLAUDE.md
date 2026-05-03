# Claude Agent — TCF Bot Instructions

## Project Overview

TCF (Transsion Core Federation) is a Telegram federation bot built with:
- Python 3.11
- python-telegram-bot 22.5 (async, PTB v22)
- Motor (async MongoDB via motor.motor_asyncio)
- Flask keepalive on port 5000

Entry point: `python3 -m tcbot`
Config: `config.env` (loaded via python-dotenv)

## Architecture

```
tcbot/
├── __init__.py          — Configs dataclass + _CfgAdapter (cfg singleton)
├── __main__.py          — Bot startup, handler registration, polling
├── alive.py             — Flask keepalive thread (port 5000)
├── database/
│   ├── mongos.py        — Motor client, connect(), col() accessor
│   ├── admins_db.py     — Owner/admin CRUD
│   ├── bans_db.py       — Federation ban CRUD (active_bans, create_ban, etc.)
│   ├── groups_db.py     — Affiliated group CRUD + pending join queue
│   ├── roles_db.py      — Developer/Tester roles (tc_roles); get_effective_role,
│   │                      role_rank, can_act_on, ROLE_RANK, ROLE_LABEL
│   ├── users_db.py      — Member cache (upsert_user, get_first_name)
│   ├── warns_db.py      — Per-group warning tracking
│   ├── kicks_db.py      — Kick log
│   ├── mutes_db.py      — Mute log
│   └── queues_db.py     — Promotion request queue
├── modules/
│   ├── __init__.py      — Module discovery, filtering, handler ordering
│   ├── messages.py      — Central M namespace for all user-facing strings
│   ├── appeals.py       — Pure functions for appeal business logic
│   ├── admins_ext.py    — Admin service layer (promote, demote, transfer ownership)
│   ├── helper/
│   │   ├── formatter.py    — HTML helpers: esc(), code(), mention(), bold()
│   │   ├── extraction.py   — extract_target(), ResolvedTarget, resolve_identity()
│   │   ├── keyboards.py    — All InlineKeyboardMarkup builders
│   │   │                     promote_role_kb(target_id, roles), demote_confirm_kb(target_id)
│   │   ├── decorators.py   — owner_only, staff_only, mod_only, basic_mod_only
│   │   ├── role_guard.py   — resolve_and_check(), auto_demote() — shared moderation helpers
│   │   ├── parse_logmsg.py — Log message text builders
│   │   │                     role_assigned, role_removed, role_auto_demoted
│   │   ├── parse_editmsg.py — safe_edit() – swallows stale-message errors
│   │   ├── ban_info.py     — build_ban_detail() shared between checking/stats
│   │   ├── parse_link.py   — message_link(), appeal_deep_link(), utcnow(),
│   │   │                     user_link(), safe_first_name(), chat_id_to_link_id()
│   │   └── workflows/      — ConversationHandler flows and executors
│   └── *.py             — Individual command modules
└── utils/
    ├── logger.py        — BotLogFormatter, setup()
    ├── prefixes.py      — build_prefixed_filters(), parse_cmd_args()
    └── timedate_format.py — fmt_dt() (tz-safe), utc_now(), utc_now_str()
```

## Key Conventions

- `cfg` is the global config accessor — always import from `tcbot`: `from tcbot import cfg`
- `db` is the database namespace — import as `from tcbot import database as db`
- All database calls are async (motor). Never use blocking pymongo calls.
- Module files expose `__handlers__`, `__module_name__`, `__help_text__`
- `__module_name__ = None` hides a module from /help
- Handler priority order defined in `modules/__init__.py` (`_PRIORITY_FIRST`, `_PRIORITY_LAST`)
- ConversationHandler timeout always uses `cfg.proof_timeout` or `cfg.appeal_timeout`

## Datetime Helpers

Two canonical sources — use the right one per context:

| Function | Location | Returns | Use when |
|---|---|---|---|
| `utc_now()` | `tcbot.utils.timedate_format` | tz-aware `datetime` | Storing timestamps in DB, building log strings |
| `fmt_dt(dt)` | `tcbot.utils.timedate_format` | `str` | Formatting any datetime for display (handles tz-naive) |
| `utcnow()` | `tcbot.modules.helper.parse_link` | naive `datetime` | Comparing against naive MongoDB timestamps |

## Role System

Four-level hierarchy stored across two collections:

| Role | Rank | Collection |
|---|---|---|
| founder | 4 | `tc_owners` |
| admin | 3 | `tc_admins` |
| developer | 2 | `tc_roles` |
| tester | 1 | `tc_roles` |

Key helpers in `tcbot.database.roles_db`:
- `get_effective_role(user_id)` → `"founder" | "admin" | "developer" | "tester" | None`
- `role_rank(role)` → int (0 for None)
- `can_act_on(executor_id, target_id)` → bool (executor rank > target rank)

Key helpers in `tcbot.modules.helper.role_guard`:
- `resolve_and_check(msg, executor_id, target_id, *, min_role)` → `(executor_role, target_role)` or `(None, None)` after replying with error
- `auto_demote(bot, target_id, target_fname, target_role, executor_id, executor_fname, action)` → removes role, logs, notifies DM

Decorator notes:
- `@decorators.mod_only` — Founder/Admin/Developer (ban/unban)
- `@decorators.basic_mod_only` — Founder/Admin/Developer/Tester (kick/mute/warn)

Auto-demote: fires on ban AND kick when target holds any role.

## Keyboard Builders (`tcbot.modules.helper.keyboards`)

Canonical function names — use these, do not invent new ones:

| Function | Purpose |
|---|---|
| `main_menu_kb()` | Main /start PM menu |
| `back_to_start_kb()` | Single « Back → start menu |
| `appeal_review_kb(ban_id)` | Approve/Reject for appeal review |
| `promo_decision_kb(request_id)` | Approve/Reject for promotion request |
| `promote_role_kb(target_id, available_roles)` | Role selection buttons for /tcpromote |
| `demote_confirm_kb(target_id)` | Confirm/Cancel for /tcdemote |
| `ban_log_new(target_id, proof_link, appeal_url)` | New ban log keyboard |
| `ban_log_update(target_id, proof_link, prev_proof_link, appeal_url)` | Updated ban log keyboard |
| `help_modules(rows, *, with_back_to_start)` | Generic help menu builder |

## What NOT To Do

- Do not add `from typing import List, Optional, Tuple` — use built-in `list`, `int | None`, `tuple`
- Do not use `datetime.utcnow()` — use `datetime.now(timezone.utc)`
- Do not add emoji to command responses unless the existing module already uses them
- Do not add dead `## comment` sections that explain obvious code
- Do not create duplicate render/keyboard functions across modules — extract shared logic
- Do not inline imports inside function bodies — keep all imports at the top of the file
- Do not use `mention(x) + code(x)` pattern — pick one per context
- Do not use `q._bot` (private PTB attribute) — use `ctx.bot` instead

## Testing

Run with: `python3 -m pytest tests/ -q`
Restart the workflow after any change: `python3 -m tcbot`
Watch for import errors before testing behavior in Telegram.
