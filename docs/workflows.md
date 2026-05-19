# Conversation Flows and Workflows - TCF Bot

This document describes how conversation flows are implemented and organized.
Before changing workflow code, consult the repository-level guidance in `agents/` for the correct conventions and approval expectations.
- `agents/RULES.md` - coding conventions, what is forbidden
- `agents/STYLE-CODE.md` - code style, typing, and formatting rules
- `agents/STYLE-COMMENTS.md` - comment and docstring style
- `agents/WORKFLOW.md` - branching, commit conventions, and deployment checklist
- `agents/CLAUDE.md` - project-specific guidance and gotchas
- `agents/REPLIT.md` - Replit environment, config, and secrets guidance

This document explains the project-specific conversation flow architecture used by the TCF bot.
It covers the code in `tcbot/modules/helper/workflows/` and the conventions for building Telegram conversations.

## Workflow structure

The `workflows/` directory contains `*_flow.py` files only.
**There are no `*_conv.py` files.** Every `ConversationHandler` is built inside a `*_flow.py` file and
exposed via a factory function (e.g. `kick_conversation(entry_fn)`, `ban_conversation(entry_fn)`).

Each `*_flow.py` file owns three concerns:
1. Executor logic (the actual moderation action)
2. State handlers (if applicable — only `ban_flow.py` and `appeal_flow.py` define their own)
3. `ConversationHandler` factory function

## Central reason + proof factory (`reason_flow.py`)

`reason_flow.py` is the single source of truth for **all** moderation conversations that require
a reason and optional proof step.

It exports:

| Export | Purpose |
|---|---|
| `WAITING_REASON = 0` | State constant — waiting for moderator to type a reason |
| `WAITING_PROOF = 1` | State constant — waiting for proof media or Skip/Cancel |
| `build_modaction_conv(...)` | Generic `ConversationHandler` factory for kick, mute, warn |
| `reason_kb(action)` | Skip + Cancel keyboard for the reason step |
| `reason_only_kb(action)` | Cancel-only keyboard (used by warn, where reason is mandatory) |
| `proof_kb(action)` | Skip + Cancel keyboard for the proof step |
| `reason_prompt(...)` | Prompt text asking for a reason |
| `reason_noted_prompt(...)` | Proof-step prompt when reason was given inline |
| `proof_step_prompt(...)` | Proof-step prompt after reason was typed in-conversation |
| `parse_inline_reason(args, has_explicit_target)` | Extract inline reason from command args |
| `record_proof(msg)` | Extract proof description from a photo/video message |

`build_modaction_conv(action, entry_fn, executor, entry_filter, reason_required, escape_filter)`
builds the complete `ConversationHandler` with all closures already wired in. Individual flow
files only supply the executor adapter and call this factory — no state handler code lives
outside `reason_flow.py`.

`ctx.user_data` keys used by the generic handlers (all prefixed by `{action}_`):

| Key | Set by | Used by |
|---|---|---|
| `{action}_target_name` or `{action}_target_fname` | Entry point | `_on_reason_text`, executor |
| `{action}_reason` | Generic `_on_reason_text` / `_on_skip_reason` | Executor |
| `{action}_proof_desc` | Generic `_on_proof` | Executor |
| `{action}_extra_info` | Entry point (optional) | `_on_reason_text`, `_on_skip_reason` |
| `{action}_prompt_chat` + `{action}_prompt_id` | Entry point (mute only) | `_on_reason_text` (edits instead of replying) |

## Ban workflow

The ban flow is self-contained in two files:

| File | Responsibility |
|---|---|
| `proof_flow.py` | `upload_proof()` — uploads proof media (single or album) to the proof channel; returns `proof_message_id` |
| `ban_flow.py` | `_execute_ban()`, `WAITING_PROOF`, album accumulators, `on_proof_received()`, `_flush_album()`, `on_cancel_proof()`, `on_proof_timeout()`, `ban_conversation(entry_fn)` |

Ban uses a separate album-aware proof mechanism and does **not** use `build_modaction_conv`.
Reason is mandatory inline (`/tcban <target> <reason>`); the conversation covers only the proof step.

Import chain (no circularity): `banning.py` → `ban_flow.py` → `proof_flow.py`

## Kick / Mute / Warn workflows

All three use `reason_flow.build_modaction_conv()` as their sole `ConversationHandler` factory.

| File | Responsibility |
|---|---|
| `kicking_flow.py` | `execute_kick()`, `_exec_kick()` adapter, `kick_conversation(entry_fn)` |
| `muting_flow.py` | `parse_duration()`, `fmt_duration()`, `_execute_mute()`, `execute_unmute()`, `_exec_mute()` adapter, `mute_conversation(entry_fn)` |
| `warning_flow.py` | `execute_warn/unwarn/warnlist/resetwarns()`, `_exec_warn()` adapter, `warn_conversation(entry_fn)` |

The `_exec_*` adapter reads all data from `ctx.user_data`, pops its own keys, and calls the real executor.

### Mute-specific note

`muting_flow._exec_mute` passes a copy of all `mute_*` keys to `_execute_mute()`, which then
edits the original prompt message via `mute_prompt_chat` / `mute_prompt_id`. The entry point
(`cmd_mute_start`) stores `mute_extra_info` (user ID + formatted duration) so the generic
`_on_reason_text` handler can display the duration in the proof-step prompt automatically.

### Warn-specific note

`build_modaction_conv` is called with `reason_required=True` for warn, which omits the Skip button
on the reason step (reason is mandatory for warnings). The `escape_filter` parameter prevents
the conversation fallback from swallowing `/tcunwarn`, `/warns`, and `/resetwarns` commands.

## Module pattern

Command module files (`kicking.py`, `muting.py`, `warnings.py`, `banning.py`) follow the
`admins.py` pattern:

1. Define the entry-point function (decorated with `@ratelimiter`, `@log_execution`, etc.)
2. Store action data in `ctx.user_data` with `{action}_*` keys
3. Call the flow's factory with the entry function
4. Expose `__handlers__` directly

```python
__handlers__ = [kick_conversation(cmd_kick_entry)]
```

No intermediate builder file. No state handler code in the module file.

## Unban workflow

`unban_flow.py` exports `execute_unban()` only. No `ConversationHandler` is needed.
`unbanning.py` registers a plain `MessageHandler` and calls `execute_unban()` directly.

## Appeal workflow

`appeal_flow.py` is a standalone `ConversationHandler` with its own deep-link entry point
and multi-step approval flow. It does not use `reason_flow.build_modaction_conv` as its
state graph is fundamentally different (reviewer approval, not moderator reason/proof collection).

## Standalone executors (no ConversationHandler)

| File | Purpose |
|---|---|
| `connected_flow.py` | Group connection and disconnection logic |
| `promote_flow.py` | `_execute_promote()`, `_ROLE_ALIASES`, `_available_roles_for()` — shared by `admins.py` |
| `stats_flow.py` | Statistics executor |
| `stats_chats_flow.py` | Chat statistics executor |

## Timeouts

Conversation timeouts come from configuration values:
- `cfg.proof_timeout` — ban, kick, mute, warn proof flows
- `cfg.appeal_timeout` — appeal flow

Keep these values in `config.env`. Do not hardcode timeouts inside conversation builders.

## Common patterns

- Use shared keyboard builders from `tcbot.modules.helper.keyboards`
- Use role helpers from `tcbot.modules.helper.role_guard`
- Keep step handlers small and delegate business logic to flow helpers
- Use `parse_editmsg.safe_edit()` to update ephemeral messages without raising stale edit errors
- Executor cleans up its own `ctx.user_data` keys before returning
- Use `asyncio.gather(..., return_exceptions=True)` for multi-group fan-out operations

## Current workflow files

```
tcbot/modules/helper/workflows/
├── reason_flow.py        — WAITING_REASON/PROOF constants + build_modaction_conv() central factory
├── proof_flow.py         — upload_proof() helper
├── ban_flow.py           — ban executor + album proof conv + ban_conversation()
├── kicking_flow.py       — kick executor + kick_conversation()
├── muting_flow.py        — mute/unmute executors + mute_conversation()
├── warning_flow.py       — warn/unwarn/warnlist/reset executors + warn_conversation()
├── unban_flow.py         — execute_unban()
├── appeal_flow.py        — standalone appeal ConversationHandler
├── connected_flow.py     — group connection flows
├── promote_flow.py       — _execute_promote() shared by admins.py
├── stats_flow.py         — stats executors
└── stats_chats_flow.py   — chat stats executors
```

## Relationship to modules

`__handlers__` in each module file contains the `ConversationHandler` (or plain `MessageHandler`)
built by calling the flow's factory function with the entry-point function as argument.

## Related documentation

- [Documentation hub](index.md)
- [Project architecture](architecture.md)
- [Modules and service boundaries](modules.md)
- [Conversation flows and workflows](workflows.md)
- [Development workflow and onboarding](development.md)
- [AI / agent guidelines](agent-guidelines.md)
- [Agent instructions for Claude](../agents/CLAUDE.md)
- [Replit environment notes](../agents/REPLIT.md)
- [Code style guidelines](../agents/STYLE-CODE.md)
- [Comment style guidelines](../agents/STYLE-COMMENTS.md)
- [Workflow expectations](../agents/WORKFLOW.md)
- [Project rules and constraints](../agents/RULES.md)
