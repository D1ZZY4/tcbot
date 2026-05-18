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

The `workflows/` directory contains two kinds of files:

- `*_flow.py` - business logic, state transition helpers, and execution functions
- `*_conv.py` - `ConversationHandler` builders and state definitions

This split keeps UI flow definitions separate from the underlying action logic.

## Naming conventions

Use this pairing pattern:

- `ban_flow.py` and `ban_conv.py` / `proof_conv.py`
- `muting_flow.py` and `muting_conv.py`
- `unban_flow.py` and `unban_conv.py`
- `kicking_flow.py` and `kicking_conv.py`
- `warning_flow.py` and `warning_conv.py`
- `appeal_flow.py` (no conv pairing)
- `stats_flow.py` and `stats_chats_flow.py`

The `*_conv.py` file is responsible for building the PTB handler and the conversation state graph.
The `*_flow.py` file is responsible for executing the feature once required information is collected.

## Ban workflow split

The ban workflow is split across four files for clarity:

| File | Responsibility |
|---|---|
| `proof_flow.py` | Uploads proof media to the proof channel; returns `proof_message_id` |
| `proof_conv.py` | Album accumulators, `on_proof_received`, `_flush_album`, `on_cancel_proof`, `on_ban_timeout`, `WAITING_PROOF` constant |
| `ban_flow.py` | `_execute_ban` - DB write, log dispatch, group enforcement |
| `ban_conv.py` | `build_handler(entry_fn)` - ConversationHandler factory for the ban flow |

Import chain (no circularity): `ban_conv` → `proof_conv` → `ban_flow` → `proof_flow`

## Unban workflow

| File | Responsibility |
|---|---|
| `unban_flow.py` | `execute_unban` - DB deactivation, group unban, log dispatch |
| `unban_conv.py` | `cmd_unban` handler, `_FILTER`, `build_handler()` |

## Kick workflow

| File | Responsibility |
|---|---|
| `kicking_flow.py` | `execute_kick` - DB log, group kick, log dispatch |
| `kicking_conv.py` | `build_handler(entry_point)` - ConversationHandler factory; reason + proof states |
| `reason_flow.py` | Shared stateless helpers: `parse_inline_reason()`, `reason_prompt()`, `reason_noted_prompt()` |

The `build_handler` factory accepts the entry-point function (`cmd_kick_entry`) from `kicking.py` to avoid circular imports. The same reason helpers are reused by the mute and warn entry points.

## Timeouts

Conversation timeouts come from configuration values.
The code uses:

- `cfg.proof_timeout` for proof-related flows
- `cfg.appeal_timeout` for appeal-related flows

Keep these values in `config.env` and do not hardcode timeouts inside the conversation builder.

## Common patterns

- Use shared keyboard builders from `tcbot.modules.helper.keyboards`
- Use role helpers from `tcbot.modules.helper.role_guard`
- Keep step handlers small and delegate business logic to flow helpers
- Use `parse_editmsg.safe_edit()` to update ephemeral messages without raising stale edit errors

## Example flow files

- `tcbot/modules/helper/workflows/proof_flow.py`
- `tcbot/modules/helper/workflows/proof_conv.py`
- `tcbot/modules/helper/workflows/ban_flow.py`
- `tcbot/modules/helper/workflows/ban_conv.py`
- `tcbot/modules/helper/workflows/unban_flow.py`
- `tcbot/modules/helper/workflows/unban_conv.py`
- `tcbot/modules/helper/workflows/connected_flow.py`
- `tcbot/modules/helper/workflows/kicking_flow.py`
- `tcbot/modules/helper/workflows/kicking_conv.py`
- `tcbot/modules/helper/workflows/muting_flow.py`
- `tcbot/modules/helper/workflows/muting_conv.py`
- `tcbot/modules/helper/workflows/appeal_flow.py`
- `tcbot/modules/helper/workflows/warning_conv.py`

## Relationship to modules

Conversation handlers are built by modules in `tcbot/modules/` and reused as the interaction model for user-facing commands.
For example, a module may import a builder from `workflows/` and add it to `__handlers__`.

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
