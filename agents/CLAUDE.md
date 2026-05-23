# AI Agent Instructions — TCF Bot

**Read this file completely before making any change to the codebase.**  
This is the primary agent reference. All other `agents/` files extend it with deeper detail on specific topics.

Compatible with: Replit AI, Claude, Gemini, Qwen, GitHub Copilot, and any AI coding agent.

---

## Project Identity

TCF Bot is a **production Telegram federation management bot** for the Transsion Core Federation community. It handles federation-wide bans, user appeals, staff role management, multi-group moderation, and full audit logging.

- **Language:** Python 3.12
- **Framework:** python-telegram-bot 22.5 (PTB v22, async, long polling — no webhook)
- **Database:** MongoDB via Motor (async)
- **Keepalive:** Flask thread on port 8080
- **Entry point:** `python3 -m tcbot`
- **Config:** Replit Secrets (`BOT_TOKEN`, `MONGODB_URI`) + Replit shared env vars (all other config)
- **Tests:** `python3 -m pytest tests/ -v` — 121 tests, all offline

---

## Architecture Map

```
tcbot/
├── __init__.py          Configs dataclass + _CfgAdapter → global cfg singleton
├── __main__.py          Startup, handler registration, polling
├── alive.py             Flask keepalive thread (port 8080)
├── database/
│   ├── cache.py         In-memory TTL caches (role, groups, owner)
│   ├── documents.py     TypedDict document shapes + Literal type aliases (BanStatus, RoleName, RequestStatus)
│   ├── types.py         NewType domain primitives: UserId, GroupId, ChatId, BanId
│   ├── mongos.py        Motor client, connect(), ensure_indexes(), col()
│   ├── admins_db.py     Owner + admin CRUD, is_owner/is_admin/is_staff
│   ├── bans_db.py       Federation ban CRUD (create, update, deactivate, query)
│   ├── groups_db.py     Connected groups + pending join queue
│   ├── roles_db.py      Developer/tester roles, get_effective_role, can_act_on
│   ├── users_db.py      Member profile cache (upsert_user, get_first_name)
│   ├── warns_db.py      Per-group warning records
│   ├── kicks_db.py      Kick log
│   ├── mutes_db.py      Mute log
│   ├── queues_db.py     Admin promotion request queue
│   └── __init__.py      Re-exports all db modules
├── modules/
│   ├── __init__.py      Module discovery + handler collection
│   ├── helper/
│   │   ├── decorators.py    owner_only, staff_only, mod_only, basic_mod_only,
│   │   │                    ratelimiter(limit, period), log_execution
│   │   ├── extraction.py    extract_target(), ResolvedTarget, resolve_identity()
│   │   ├── formatter.py     esc(), code(), mention(), bold()
│   │   ├── keyboards.py     All InlineKeyboardMarkup factory functions
│   │   ├── role_guard.py    resolve_and_check(), auto_demote()
│   │   ├── ban_info.py      build_ban_detail() — shared ban renderer
│   │   ├── parse_link.py    message_link(), appeal_deep_link(), user_link()
│   │   ├── parse_logmsg.py  Log message text builders
│   │   ├── parse_editmsg.py safe_edit() — swallows stale-message errors
│   │   └── workflows/
│   │       ├── reason_flow.py      BuildReason class + build_modaction_conv() + WAITING_REASON/PROOF constants + parse_inline_reason()
│   │       ├── proof_flow.py       BuildProof class (keyboard/step_prompt/noted_prompt/record) + upload_proof()
│   │       ├── ban_flow.py         proof instance (skip_allowed=False) + album-aware ban proof ConversationHandler
│   │       ├── appeal_flow.py      appeal instance + BuildAppeal (instruction_text/cancel_keyboard/review_keyboard/on_decision/build_handler)
│   │       ├── kicking_flow.py     reason/proof instances + execute_kick(), kick_conversation(entry_fn)
│   │       ├── muting_flow.py      reason/proof instances + _execute_mute(), execute_unmute(), mute_conversation()
│   │       ├── warning_flow.py     reason/proof instances + execute_warn/unwarn/warnlist/resetwarns(), warn_conversation()
│   │       ├── unban_flow.py       execute_unban() — no ConversationHandler needed
│   │       ├── promote_flow.py     _execute_promote(), shared by admins.py
│   │       ├── connected_flow.py   connection instance + BuildConnection (join_prompt/connected_message/check_perms/complete_join/on_bot_added/on_join_decision)
│   │       ├── stats_flow.py       Statistics executors
│   │       └── stats_chats_flow.py Chat statistics executors
│   └── *.py             Command modules (banning, muting, kicking, warnings, appeals, …)
└── utils/
    ├── dispatch.py      fan_out() — semaphore-bounded multi-group dispatcher (max 10)
    ├── error_reporter.py 3-layer error classification and Telegram reporting
    ├── logger.py        BotLogFormatter, setup()
    ├── prefixes.py      build_prefixed_filters(), parse_cmd_args(), filter constants
    └── timedate_format.py utc_now(), to_utc(), fmt_dt(), utc_now_str()
```

---

## Global Import Pattern

```python
from tcbot import cfg            # config adapter — always use cfg, never configs
from tcbot import database as db # database namespace — db.bans_db, db.groups_db, etc.
```

Never import `configs` (the raw dataclass) in module code. Always use `cfg`.

---

## Role System

### Hierarchy

| Role | Rank | Collection | Permissions |
|---|---|---|---|
| founder | 4 | `tc_owners` | All actions + ownership transfer |
| admin | 3 | `tc_admins` | Ban/unban/kick/mute/warn + promote developer/tester |
| developer | 2 | `tc_roles` | Ban/unban/kick/mute/warn |
| tester | 1 | `tc_roles` | Kick/mute/warn |

### Canonical Helpers — Always Use These

```python
from tcbot.database.roles_db import get_effective_role, role_rank, can_act_on, ROLE_RANK, ROLE_LABEL

# Resolve effective role (cached 60s, invalidated on writes):
role = await get_effective_role(user_id)
# → "founder" | "admin" | "developer" | "tester" | None

# Numeric rank (0 for None):
role_rank("developer")  # → 2
role_rank(None)         # → 0

# Permission check (executor must strictly outrank target):
ok = await can_act_on(executor_id, target_id)
```

**NEVER** chain `is_owner()` + `is_admin()` + `get_role()` manually. Always call `get_effective_role()`.

### Auto-Demote

Call `auto_demote()` **before** executing any ban or kick when the target holds a role:

```python
from tcbot.modules.helper.role_guard import auto_demote

target_role = await get_effective_role(target_id)
if target_role:
    await auto_demote(
        ctx.bot,
        target_id, target_fname, target_role,
        executor_id, executor_fname, "ban",  # or "kick"
    )
# Then proceed with the ban/kick
```

`auto_demote()` removes the role from DB, sends the user a DM notification, and posts a log entry.

### Role Guard Helper

For commands that need to validate executor and target roles simultaneously:

```python
from tcbot.modules.helper.role_guard import resolve_and_check

executor_role, target_role = await resolve_and_check(
    msg, executor_id, target_id, min_role="developer"
)
if executor_role is None:
    return  # resolve_and_check already replied with the appropriate error
```

---

## Decorator Stack

Every command handler and callback handler **must** carry all three decorators in this exact order (outermost to innermost):

```python
@decorators.ratelimiter(limit=5, period=60)   # OUTERMOST — rate checked first
@decorators.mod_only                          # AUTH GUARD — checked second
@decorators.log_execution                     # INNERMOST — logs after auth passes
async def cmd_ban_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ...
```

When there is no auth guard:

```python
@decorators.ratelimiter(limit=8, period=30)
@decorators.log_execution
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...
```

Message-event handlers (e.g. `on_new_member` in `greeting.py`) are **exempt** from rate limiters.

### Standard Rate Limits

| Category | limit | period |
|---|---|---|
| Destructive (ban, kick, unban, broadcast) | 3–5 | 60 |
| Moderation (mute, warn, cleanup) | 3–5 | 60 |
| Read commands (stats, groups, checkme, help) | 8 | 30 |
| Inline callbacks (button presses) | 15 | 30 |
| Emergency-only (leaveall) | 1 | 300 |

---

## Conversation Flow Pattern

**There are NO `*_conv.py` files in this project.** Every `ConversationHandler` is built inside a `*_flow.py` file via a factory function. Module files define `*_CMDS` filters, the entry point, and `__handlers__` (same pattern as `admins.py`):

```python
# kicking.py — canonical pattern
from tcbot.modules.helper.workflows.kicking_flow import kick_conversation
from tcbot.utils.prefixes import build_prefixed_filters

_KICK_CMDS = build_prefixed_filters("tckick") | build_prefixed_filters("tck")

__handlers__ = [kick_conversation(cmd_kick_entry, _KICK_CMDS)]
```

### Kick / Mute / Warn — use `reason_flow.build_modaction_conv()`

`kick_conversation()`, `mute_conversation()`, `warn_conversation()` are thin wrappers. Each defines an executor adapter (`_exec_kick`, `_exec_mute`, `_exec_warn`) and calls `reason_flow.build_modaction_conv()`.

States: `WAITING_REASON = 0`, `WAITING_PROOF = 1`

### Ban — `ban_flow.ban_conversation(entry_fn)`

Album-aware proof flow (no reason step, buffered album handling). State: `WAITING_PROOF`. Entry must return `WAITING_PROOF` or `ConversationHandler.END`.

### Appeal — `appeal_flow.build_handler()`

Standalone ConversationHandler. Entry: `/start appeal_<ban_id>`. Completely independent of `reason_flow`.

### Timeouts — Always Use Config Values

```python
# proof flows
cfg.proof_timeout        # not a hardcoded integer

# appeal flow
cfg.appeal_timeout
```

---

## Keyboard Builders

All keyboard builders live in `tcbot/modules/helper/keyboards.py`. Do not create keyboard functions anywhere else.

| Function | Purpose |
|---|---|
| `main_menu_kb()` | Main /start PM menu |
| `back_to_start_kb()` | « Back → start menu |
| `back_to_help_kb()` | « Back → help_menu (menu path) |
| `back_to_help_cmd_kb()` | « Back → helpc_main (command path) |
| `appeal_review_kb(ban_id)` | Approve/Reject for appeal review cards |
| `promo_decision_kb(request_id)` | Approve/Reject for promotion requests |
| `promote_role_kb(target_id, available_roles)` | Role selection for /tcpromote |
| `demote_confirm_kb(target_id)` | Confirm/Cancel for /tcdemote |
| `ban_log_new(target_id, proof_link, appeal_url)` | New ban log keyboard |
| `ban_log_update(target_id, proof_link, prev_proof_link, appeal_url)` | Updated ban log keyboard |
| `help_modules(rows, *, with_back_to_start)` | Generic help menu builder |
| `cancel_proof_kb()` | Cancel button during ban proof step |
| `join_group_kb()` | Connect/Cancel for group join prompt |
| `checkme_ban_kb(bot_username, ban_id, proof_link)` | Summary view for /checkme |
| `checkme_detail_back_kb(ban_id, proof_link)` | Detail view for /checkme |

---

## HTML Formatting

All user-facing messages must use `parse_mode="HTML"`. Canonical helpers from `tcbot/modules/helper/formatter.py`:

```python
from tcbot.modules.helper.formatter import esc, code, mention, bold

esc(user_input)        # Escape &, <, > — ALWAYS use on user-provided strings
code("123456789")      # <code>123456789</code>
mention(uid, fname)    # <a href="tg://user?id=uid">fname</a>
bold("text")           # <b>text</b>
```

Multi-line message strings use parenthesized concatenation, not backslash continuation:

```python
text = (
    "<b>Ban Information</b>\n\n"
    f"User: {mention(uid, fname)}\n"
    f"Ban ID: {code(ban_id)}"
)
```

---

## Target Resolution

```python
from tcbot.modules.helper.extraction import extract_target

target_id, target_fname = await extract_target(update, args, ctx.bot)
# Returns (None, None) if no valid target can be resolved
```

Resolution order (explicit args always win):
1. `args[0]` as numeric ID or `@username`
2. Reply-to-message sender (only when no explicit arg)
3. `text_mention` entity
4. `@mention` entity resolved via `bot.get_chat()`

---

## Datetime Helpers

Use the correct function for each context:

| Function | Location | Returns | Use when |
|---|---|---|---|
| `utc_now()` | `tcbot.utils.timedate_format` | tz-aware `datetime` | Storing timestamps in DB, elapsed-time checks |
| `to_utc(dt)` | `tcbot.utils.timedate_format` | tz-aware `datetime` | Normalizing before subtracting datetimes |
| `fmt_dt(dt)` | `tcbot.utils.timedate_format` | `str` | Displaying any datetime to users |
| `utc_now_str()` | `tcbot.utils.timedate_format` | `str` | One-line formatted current time |

Import all datetime helpers from `tcbot.utils.timedate_format` only. Never use `datetime.utcnow()` or `datetime.now(timezone.utc)` outside that module.

---

## Multi-Group Operations

Use `fan_out()` for any operation touching multiple groups:

```python
from tcbot.utils.dispatch import fan_out

groups  = await db.groups_db.active_groups()
results = await fan_out([
    ctx.bot.ban_chat_member(g["chat_id"], target_id)
    for g in groups
])
errors = sum(1 for r in results if isinstance(r, BaseException))
```

`fan_out()` caps concurrency at 10, never raises, returns results in input order.

---

## Bot Persona — Role-Aware Responses

Required pattern for every command that targets a user:

```python
# 1. Bot self-check
if target_id == ctx.bot.id:
    await msg.reply_text("That's me — [context]. 😄", parse_mode="HTML")
    return

# 2. Role check via get_effective_role (NEVER chain is_owner/is_admin/get_role)
target_role = await get_effective_role(target_id)
if target_role == "founder":
    fname = await db.users_db.get_first_name(target_id, "the Founder")
    await msg.reply_text(
        f"That's {mention(target_id, fname)}, our Founder — [context]. 👑",
        parse_mode="HTML",
    )
    return
if target_role in ("admin", "developer", "tester"):
    label = ROLE_LABEL.get(target_role, target_role.capitalize())
    fname = await db.users_db.get_first_name(target_id, str(target_id))
    await msg.reply_text(
        f"That's a {cfg.community_name} {label} — [context].",
        parse_mode="HTML",
    )
    return  # or proceed, depending on the action
```

Tone: friendly-formal. 1–3 emojis per message where natural. Short and direct. No filler phrases.

---

## Database Rules

1. All write operations must live in `tcbot/database/`, never in module handlers.
2. Never call `col()` directly from module code — use per-collection helper functions.
3. All helpers must be async and fully typed.
4. Index-sensitive queries must match the indexes in `mongos.ensure_indexes()`.
5. Always `await q.answer()` before any further action in a `CallbackQueryHandler`.
6. Wrap every `bot.send_message` / `bot.ban_chat_member` / etc. in try/except when iterating over groups — one failure must not abort the loop.

---

## Module File Checklist

When creating or editing `tcbot/modules/*.py`:

- [ ] `from __future__ import annotations` as first non-comment line
- [ ] Copyright header (3 lines: Transsion Core, Dizzy, Aveum Apps)
- [ ] One-line module docstring
- [ ] `__module_name__` set (or `= None` to hide from /help)
- [ ] `__help_text__` set if `__module_name__` is not `None`
- [ ] All command/callback handlers carry the 3-layer decorator stack
- [ ] `__handlers__` list at the bottom of the file
- [ ] No inline imports inside function bodies
- [ ] No raw `col()` calls — all DB access via `db.*_db.*`

---

## What NOT To Do

- Do not use `from typing import List, Optional, Tuple` — use `list`, `int | None`, `tuple`
- Do not use `datetime.utcnow()` or inline `datetime.now(timezone.utc)` — use `tcbot.utils.timedate_format` only
- Do not use `q._bot` (private PTB attribute) — use `ctx.bot`
- Do not create `*_conv.py` files — ConversationHandlers belong in `*_flow.py`
- Do not duplicate reason/proof state handlers — use `reason_flow.build_modaction_conv()`
- Do not create new keyboard functions in module files — extend `keyboards.py`
- Do not inline imports inside function bodies
- Do not silently swallow exceptions with bare `pass` — always `log.debug()` at minimum
- Do not store `Update` or `Message` objects beyond the handler call lifetime
- Do not mix `parse_mode="Markdown"` and `parse_mode="HTML"` — always use HTML
- Do not add packages to `requirements.txt` — managed via `pyproject.toml`

---

## Testing

```bash
python3 -m pytest tests/ -v
```

All 121 tests run offline — no bot token or MongoDB connection required.

After any code change:
1. Run all tests — all 121 must pass
2. Restart the `Start application` workflow
3. Verify startup logs: no import errors, MongoDB connected, handlers registered

---

## Related Files

| File | Purpose |
|---|---|
| `agents/RULES.md` | Complete project rules and constraints |
| `agents/STYLE-CODE.md` | Code style, typing, naming, alignment, decorator order |
| `agents/STYLE-COMMENTS.md` | Comment and docstring conventions |
| `agents/WORKFLOW.md` | Branching, commit messages, deployment checklist |
| `agents/REPLIT.md` | Replit environment, secrets, workflow, ports |
| `docs/architecture.md` | Startup flow, DB schema, caching, error handling |
| `docs/modules.md` | Per-module responsibilities and boundaries |
| `docs/workflows.md` | ConversationHandler flows in full detail |
| `docs/development.md` | Setup, onboarding, adding modules and collections |
| `PLAN.md` | Bug priorities, improvement strategy, session tracker |
