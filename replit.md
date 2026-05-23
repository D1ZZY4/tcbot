# TCF Telegram Bot

## Overview

A Telegram bot for the Transsion Core Federation (TCF) community. Manages federation-wide bans, appeals, group affiliations, admin promotions, and moderation.

## Architecture

- **Language:** Python 3.13
- **Bot framework:** python-telegram-bot 22.5 (polling mode)
- **Database:** MongoDB (via motor, async)
- **Web server:** Flask (keep-alive / health-check on port 5000)
- **Entry point:** `python3 -m tcbot`
- **Dependency management:** `uv` (lock file: `uv.lock`; `requirements.txt` is legacy and git-ignored)

## Key Modules

| Path | Purpose |
|---|---|
| `tcbot/__init__.py` | Config singleton (`cfg` / `configs`), loaded from env vars |
| `tcbot/__main__.py` | Entry point: logging, Flask keepalive, handler discovery, polling |
| `tcbot/alive.py` | Flask keep-alive server on port 5000 |
| `tcbot/database/mongos.py` | MongoDB client, `connect()`, `col()`, `make_short_id()` |
| `tcbot/database/admins_db.py` | Owners and TC admins collection |
| `tcbot/database/bans_db.py` | Federation bans collection |
| `tcbot/database/queues_db.py` | Promotion-request queue collection |
| `tcbot/database/roles_db.py` | Developer/Tester roles collection (`tc_roles`); also exports `get_effective_role`, `role_rank`, `can_act_on` |
| `tcbot/database/users_db.py` | Member-cache collection |
| `tcbot/modules/appeals.py` | Pure functions for appeal business logic |
| `tcbot/database/types.py` | Domain primitive `NewType` definitions: `UserId`, `GroupId`, `ChatId`, `BanId` |
| `tcbot/modules/helper/parse_link.py` | Link builders, HTML helpers (`user_link`, `safe_first_name`) |
| `tcbot/modules/helper/keyboards.py` | All inline-keyboard factory functions (includes `promote_role_kb`, `demote_confirm_kb`) |
| `tcbot/modules/helper/decorators.py` | Auth decorators (`owner_only`, `staff_only`, `mod_only`, `basic_mod_only`) + `log_execution` tracer + `ratelimiter(limit, period)` per-user throttle |
| `tcbot/modules/helper/role_guard.py` | `resolve_and_check()` + `auto_demote()` - shared role-permission helpers for moderation flows |
| `tcbot/modules/helper/extraction.py` | `extract_target()`, `ResolvedTarget`, `resolve_identity()` |
| `tcbot/modules/helper/workflows/promote_flow.py` | `_execute_promote()`, `_ROLE_ALIASES`, `_available_roles_for()` — promote execution logic shared by admins.py |
| `tcbot/modules/helper/workflows/reason_flow.py` | `BuildReason` class + `build_modaction_conv(reason, proof, ...)` factory + `WAITING_REASON`/`WAITING_PROOF` constants + `parse_inline_reason()`. `BuildReason(action, *, skip_allowed, skip_label, cancel_label)` — `.keyboard()` and `.prompt()` |
| `tcbot/modules/helper/workflows/proof_flow.py` | `BuildProof` class + `upload_proof()`. `BuildProof(action, *, skip_allowed, skip_label, cancel_label)` — `.keyboard()`, `.step_prompt()`, `.noted_prompt()`, `.record()` (static) |
| `tcbot/modules/helper/workflows/ban_flow.py` | Ban executor, album proof state handlers, `ban_conversation(entry_fn)` |
| `tcbot/modules/helper/workflows/appeal_flow.py` | `BuildAppeal` class + module-level `appeal` instance. `BuildAppeal(community_name, log_channel, *, cancel_label, cancel_callback)` — `.instruction_text()`, `.cancel_keyboard()`, `.review_keyboard(ban_id)`, `.on_decision()`, `.build_handler()` |
| `tcbot/modules/helper/workflows/connected_flow.py` | `BuildConnection` class + module-level `connection` instance. `BuildConnection(community_name, *, required_perms, join_label, cancel_label, join_callback, cancel_callback)` — `.join_prompt()`, `.connected_message()`, `.check_perms()`, `.complete_join()`, `.on_bot_added()`, `.on_join_decision()` |
| `tcbot/utils/dispatch.py` | `fan_out()` — semaphore-bounded multi-group dispatcher (max 10 concurrent) |
| `tcbot/utils/prefixes.py` | Prefix filter builder + alt-prefix dispatcher (`_REGISTRY`) |
| `tcbot/utils/logger.py` | `BotLogFormatter` and `setup()` |
| `tcbot/utils/timedate_format.py` | `utc_now()`, `to_utc()`, `fmt_dt()`, `utc_now_str()` — single datetime source |

## Configuration

**All configuration and secrets are stored exclusively in `config.env`.** Do NOT use Replit Secrets for this project. `config.env` is gitignored and must never be committed.

- `BOT_TOKEN` - Telegram bot token
- `MONGODB_URI` - MongoDB connection string
- `OWNER_ID` - Initial owner Telegram user ID
- `DB_NAME` - MongoDB database name (default: "tcbot")
- `MAIN_GROUP` - Main Telegram group/forum chat ID
- `PORT` - Web server port (5000)

See `config.env.example` for the full list of required keys.

## Role System

Four-level hierarchy: **Founder → Admin → Developer → Tester**

| Role | Rank | Stored in |
|---|---|---|
| Founder | 4 | `tc_owners` (single document) |
| Admin | 3 | `tc_admins` collection |
| Developer | 2 | `tc_roles` collection |
| Tester | 1 | `tc_roles` collection |

Permission matrix:

| Action | Min role needed |
|---|---|
| Ban / Unban | Developer (rank ≥ 2) |
| Kick / Mute / Warn | Tester (rank ≥ 1) |
| Promote to Developer/Tester | Admin |
| Promote to Admin | Admin (request) / Founder (direct) |
| Demote Developer/Tester | Admin |
| Demote Admin | Founder only |

Auto-demote: when a user with any role is **banned or kicked**, their role is automatically removed and they are notified by DM. A log entry is posted to the log channel.

`/tcpromote @user [role]` - omit the role to see an inline button menu.
`/tcdemote @user` - shows a confirmation button before removing the role.

## Test Suite

Run with: `python3 -m pytest`

134 tests across 13 files - all pass offline (no real bot token or MongoDB needed).
Test dependencies: `pip install pytest pytest-asyncio` (Replit) or `uv sync --extra test` (local).

| File | What it tests |
|---|---|
| `tests/test_format.py` | `tcbot.modules.helper.parse_link` helpers |
| `tests/test_targets.py` | `ResolvedTarget` and `get_reason` |
| `tests/test_users_resolver.py` | `resolve_identity` with mocked repos |
| `tests/test_prefix.py` | Alt-prefix dispatcher and registry |
| `tests/test_keyboards.py` | `tcbot.modules.helper.keyboards` factory shapes |
| `tests/test_decorators.py` | `log_execution` tracer decorator |
| `tests/test_appeals_pure.py` | Pure appeal logic functions |
| `tests/test_log_templates.py` | `parse_logmsg` log-message formatters |
| `tests/test_bans_db.py` | `bans_db` helpers (create, update, deactivate) |
| `tests/test_ban_flow.py` | Ban flow album buffering and state |
| `tests/test_config_parse.py` | Config parsing (`parse_list`, `parse_port`, `parse_chat_id`) |
| `tests/test_rate_limiter.py` | `_RateLimiter` sliding-window logic |
| `tests/test_users_resolver.py` | `resolve_identity` with mocked repos |
| `tests/test_warns_db.py` | `warns_db` helpers (add, remove, reset) |

## Docker

```
docker-compose up --build
```

- `Dockerfile` - uses `uv` (`COPY --from=ghcr.io/astral-sh/uv:latest`) with `uv sync --frozen --no-dev`
- `docker-compose.yml` - `bot` + `mongo:7` services; bot waits for MongoDB health-check

## Agent Instructions

Before making any changes, **read all documentation files in the `agents/` directory** - specifically:
- `agents/RULES.md` - coding conventions, what is forbidden
- `agents/STYLE-CODE.md` - code style, typing, and formatting rules
- `agents/STYLE-COMMENTS.md` - comment and docstring style
- `agents/WORKFLOW.md` - branching, commit conventions, and deployment checklist
- `agents/CLAUDE.md` - project-specific guidance and gotchas
- `agents/REPLIT.md` - Replit environment, config, and secrets guidance

## Related documentation

- [Documentation hub](docs/index.md)
- [Project architecture](docs/architecture.md)
- [Modules and service boundaries](docs/modules.md)
- [Conversation flows and workflows](docs/workflows.md)
- [Development workflow and onboarding](docs/development.md)
- [AI / agent guidelines](docs/agent-guidelines.md)
- [Agent instructions for Claude](agents/CLAUDE.md)
- [Code style guidelines](agents/STYLE-CODE.md)
- [Comment style guidelines](agents/STYLE-COMMENTS.md)
- [Workflow expectations](agents/WORKFLOW.md)
- [Project rules and constraints](agents/RULES.md)

## Deployment

- Workflow: `python3 -m tcbot`
- Port 5000 exposed as the health-check / keep-alive endpoint
- Deployment target: **autoscale**, run command: `python3 -m tcbot`
- DO NOT CHANGE CONFIG.ENV OR ANYTHING, AND RUN THIS PROJECT THROUGH CONFIG.ENV ONLY. DO NOT USE REPLIT SECRET. DO NOT CHANGE ANYTHING!!!
- DO NOT ADD ANY PACKAGES IN REQUIREMENTS!!
