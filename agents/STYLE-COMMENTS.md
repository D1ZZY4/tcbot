# Comment Style - TCF Bot

Before making any changes, **read all documentation files in the `agents/` directory** - specifically:
- `agents/RULES.md` - coding conventions, what is forbidden
- `agents/STYLE-CODE.md` - code style, typing, and formatting rules
- `agents/STYLE-COMMENTS.md` - comment and docstring style
- `agents/WORKFLOW.md` - branching, commit conventions, and deployment checklist
- `agents/CLAUDE.md` - project-specific guidance and gotchas
- `agents/REPLIT.md` - Replit environment, config, and secrets guidance

## Module Docstring

Every file starts with the copyright header, then a one-line module docstring:

```python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Short/Long description of what this module does.
"""

from __future__ import annotations
```

The docstring is a single sentence. No period needed for one-liners.
Multi-line docstrings are allowed for complex modules (e.g. mute_flow.py with its flow diagram).

## Function Docstrings

Write docstrings only when the function's purpose is not immediately obvious from its name and signature.
Keep them concise - one sentence or a short paragraph. No `:param:` / `:returns:` Sphinx tags.

```python
async def sweep_group(self, chat_id: int) -> tuple[int, int]:
    """
    Ban all currently-present federation-banned members in `chat_id`.

    Returns (banned_count, error_count). Individual errors do not abort
    the sweep.

    ! WARNING: Long or short description.
    ! CRITICAL: long or Short description.
    TODO: Long or short description.
    NOTE: Long or short description.
    ? Long or short question description.
    * Long or short highlight or information or general description.
    """
```

Obvious helper functions do not need docstrings:
```python
def _strip_chat_id(chat_id: int) -> str:
    return str(chat_id).replace("-100", "")
```

## Inline Comments

Use `##` (double hash) for section-level inline comments. Use `#` only for brief end-of-line notes.

```python
# * Apply all existing federation bans
bans = await db.bans_db.active_bans()
applied = 0
for ban in bans:
    ...
```

Do not comment what the code already says:
```python
# ! Bad
# * Increment applied counter
applied += 1

# * Good - no comment needed
applied += 1
```

## TODO / FIXME

Use `## TODO:` for deferred improvements. Include enough context to act on it:
```python
# TODO: batch ban calls with asyncio.gather() once rate-limit handling is in place
for grp in groups:
    await bot.ban_chat_member(grp["chat_id"], target_id)
```


## Section Dividers

Use the following style to separate logical sections. The title line must be exactly **70 characters** wide with the text centered and flanked by `#` and `─` characters.
The Section Title should be concise but descriptive of the content below. Use this style for major sections within a handler or function, but not for every minor block.

```python
# ────────────────────────── Section Title ───────────────────────── #
# ! WARNING: Short or Long Warning Description
# ! CRITICAL: Short or Long Critical Description
# TODO: Short or Long Description
# NOTE: Short or Long Note Description
# ? Short or Long Question Description
# * Short or Long Highlight or Information or General Description
```
or use a docstring for longer descriptions:
```python
# ────────────────────────── Section Title ───────────────────────── #
"""
! WARNING: Short or Long Warning Description
! CRITICAL: Short or Long Critical Description
! TODO: Short or Long Description
! NOTE: Short or Long Note Description
! ? Short or Long Question Description
! * Short or Long Highlight or Information or General Description
"""
```
```python
async def RateLimitHandler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handle rate-limited updates by notifying the user and logging the event.

    ! WARNING: This handler is triggered when the bot receives too many requests in a short period.
    ! CRITICAL: Ensure that this handler does not cause further rate limits or crashes.
    TODO: Consider implementing an exponential backoff strategy for repeated rate limits.
    NOTE: This handler should be added to the ConversationHandler states where rate limits are likely.
    ? Should we notify the bot owner or log this event to a specific channel for monitoring?
    * This handler helps maintain a good user experience by informing users about rate limits and prevents the bot from crashing due to unhandled exceptions.
    """
    await msg.reply_any(update, "⚠️ Too many requests! Please slow down and try again in a bit.")
```

Keep dividers consistent in length (70 dashes). Do not use them for every 5-line block -
only for genuinely distinct sections (e.g. keyboard builders vs. handlers vs. handler factory).

## What Not To Comment

- Do not comment imports
- Do not add "Legacy compat" or "Deprecated" blocks - remove dead code outright
- Do not explain Python syntax
- Do not add `# noqa` without a reason in the same comment
## Related documentation

- [Documentation hub](../docs/index.md)
- [Project architecture](../docs/architecture.md)
- [Modules and service boundaries](../docs/modules.md)
- [Conversation flows and workflows](../docs/workflows.md)
- [Development workflow and onboarding](../docs/development.md)
- [AI / agent guidelines](../docs/agent-guidelines.md)
