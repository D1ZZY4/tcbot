---
name: Module structure
description: Snapshot of the TCF Bot source layout after refactoring. Use this to orient quickly in new sessions.
---

# TCF Bot — Module Structure

**Last updated:** 2026-06-02

## Repository layout

```
tcbot/
├── __init__.py              Configs dataclass, global cfg adapter, env parsing
├── __main__.py              Startup: Flask keepalive, PTB app, MongoDB, polling
├── alive.py                 Flask health check on PORT (default 5000, Replit 8080)
├── database/
│   ├── bans_db.py           Federation bans (active_bans, get_ban, add_ban, etc.)
│   ├── cache.py             In-memory TTL cache (RoleCache, UserCache)
│   ├── documents.py         TypedDict document shapes and Literal aliases
│   ├── groups_db.py         Connected groups, join queue, active_groups
│   ├── kicks_db.py          Kick log (log_kick, user_kicks, user_kick_count)
│   ├── mongos.py            Motor client, connect(), ensure_indexes(), col()
│   ├── mutes_db.py          Mute log (log_mute, user_mutes, user_mute_count)
│   ├── queues_db.py         Promotion request queue
│   ├── types.py             NewType domain primitives
│   ├── users_cache.py       Member profile cache (get_user, get_mention_data_batch, etc.)
│   ├── users_roles.py       Roles: owner, admin, developer, tester; role_meta, can_act_on
│   └── warns_db.py          Warning records (add_warn, get_warns, user_total_warns, etc.)
├── modules/
│   ├── __init__.py          Dynamic module loader (discover, allowlist, denylist)
│   ├── about.py             /tcabout command
│   ├── additional.py        Additional utility commands
│   ├── admins.py            /tcadmins — staff list
│   ├── appeals.py           /appeal entry point
│   ├── banning.py           /ban, /unban entry points
│   ├── broadcasting.py      /broadcast command
│   ├── checking.py          /check, /checkme entry points
│   ├── connecting.py        Group connection management
│   ├── disconnecting.py     Group disconnection
│   ├── greeting.py          New-member welcome handler
│   ├── groups.py            /tcgroups — connected group list
│   ├── help.py              /help, /start help text
│   ├── kicking.py           /kick entry point
│   ├── maintenance.py       Maintenance/admin commands
│   ├── muting.py            /mute entry point
│   ├── privacy.py           /privacy command
│   ├── start.py             /start
│   ├── stats.py             /tcstats entry point
│   ├── unbanning.py         /unban entry point
│   ├── warnings.py          /warn, /unwarn, /warnlist, /resetwarns entry points
│   └── helper/
│       ├── ban_info.py      build_ban_detail() — shared ban card renderer
│       ├── decorators.py    Auth guards, rate limiter, log_execution, resolve_and_check
│       ├── extraction.py    extract_target() — user resolution from reply/arg/entity
│       ├── formatter.py     bold(), code(), esc(), mention(), italic(), link()
│       ├── identity.py      classify(), refuse_message(), staff_notice()
│       ├── keyboards.py     All inline keyboard factory functions
│       ├── parse_editmsg.py Edit-message log helpers
│       ├── parse_link.py    Telegram link parsing helpers
│       ├── parse_logmsg.py  Audit log message builders (ban_log, kick_log, etc.)
│       └── workflows/
│           ├── appeal_flow.py     BuildAppeal ConversationHandler factory
│           ├── ban_flow.py        Ban proof collection, album buffering, federation ban
│           ├── check_flow.py      Check class: profile, bans, warns, kicks, mutes, appeals
│           ├── connected_flow.py  Group join approval, BuildConnection
│           ├── demote_flow.py     Demote class: auto-demote on ban/kick, manual demote
│           ├── kicking_flow.py    execute_kick()
│           ├── muting_flow.py     execute_mute()
│           ├── promote_flow.py    Promote class: role promotion, request queue
│           ├── proof_flow.py      BuildProof: upload_proof, step prompts
│           ├── reason_flow.py     BuildReason: build_modaction_conv() factory
│           ├── stats_flow.py      Stats class: overview, staff, users, chats, bans, search
│           ├── unban_flow.py      execute_unban()
│           └── warning_flow.py   execute_warn(), execute_unwarn(), execute_warnlist(), etc.
└── utils/
    ├── dispatch.py          fan_out() bounded async fan-out for multi-group ops
    ├── error_reporter.py    Async error reporting to configured Telegram destination
    ├── logger.py            Logging configuration (BotLogFormatter, TelegramErrorHandler, setup)
    ├── pagination.py        paginate(), nav_row(), date_or_unknown() — shared paginators
    ├── prefixes.py          build_prefixed_filters() — command filter builder
    └── timedate_format.py   utc_now(), fmt_dt(), to_utc(), utc_now_str()

tests/                       70 offline pytest files, 1337 tests (asyncio_mode=auto, no real Telegram/MongoDB)
docs/                        Architecture docs, feature guides, module references
.agents/                     Agent policy, style, workflow, skills, memory
```

## Key cross-cutting constraints

- All MongoDB writes: `tcbot/database/*_db.py` only. No `col()` in modules.
- All keyboard builders: `tcbot/modules/helper/keyboards.py` only.
- All conversation flows: `tcbot/modules/helper/workflows/*_flow.py` only. Never `*_conv.py`.
- Pagination: `paginate(items, page, _PAGE_SIZE)` from `tcbot.utils.pagination`. Never private wrappers.
- Bot messages: `parse_mode="HTML"`, escape with `esc()`. No Markdown mode. No emoji in bot output.
- Datetime: `utc_now()`, `fmt_dt()`, `to_utc()` from `tcbot.utils.timedate_format`. Never `utcnow()`.
- Async: `asyncio.gather()` for independent operations; `fan_out()` for multi-group Telegram ops.
