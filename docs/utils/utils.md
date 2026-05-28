# Runtime Utilities

Runtime utilities live in `tcbot/utils/`. They provide infrastructure used across command modules, workflows, database helpers, and startup.

## `dispatch.py`

`fan_out(coros, max_concurrent=10)` runs awaitables concurrently with a semaphore.

Behavior:

- preserves input order in the returned list;
- returns exceptions as list elements instead of raising;
- returns an empty list for empty input;
- defaults to 10 concurrent tasks, which is safe for Telegram API fan-out operations.

Use it for multi-group actions such as ban, unban, mute, broadcast, and cleanup.

```python
results = await fan_out([
    ctx.bot.ban_chat_member(group["chat_id"], target_id)
    for group in groups
])
errors = sum(1 for item in results if isinstance(item, BaseException))
```

## `prefixes.py`

Command prefix support is centralized here.

| Export | Purpose |
|---|---|
| `build_prefixed_filters(command)` | Builds a PTB message filter matching any configured prefix plus an exact lowercase command. |
| `parse_cmd_args(text)` | Returns command arguments after the first whitespace. |
| `register_command(name, callback)` | Registers an async callback for alternate-prefix dispatch. |
| `dispatch_alt_prefix(update, context)` | Dispatches configured non-slash prefix commands from the registry. |
| `ANY_CMD_FILTER` / related filters | Shared command-detection filters used to avoid treating commands as plain text. |

`PREFIXES` supports a Python-style list such as `["/", "!", "."]` and falls back to common prefixes when unset. Prefix filters are case-sensitive, accept lowercase ASCII command names, and only accept `@BotName` suffixes that target the current bot.

## `logger.py`

Logging setup is installed from `tcbot.__main__.main()`.

| Export | Purpose |
|---|---|
| `BotLogFormatter` | Console formatter with time, date, module, line, level, and message. |
| `TelegramErrorHandler` | Logging handler that forwards error-level records to `error_reporter`. |
| `setup(level=logging.INFO)` | Installs console and Telegram error handlers on the root logger and quiets noisy libraries. |

Third-party loggers such as `httpx`, `telegram`, `motor`, and `pymongo` are capped to reduce noise.

## `error_reporter.py`

Error reporting sends structured HTML messages to `LOGS_ERRORS`.

| Export | Purpose |
|---|---|
| `attach(bot, chat_id, thread_id)` | Stores the live bot and destination after PTB startup. |
| `build_error_message(exc=None, record=None, context=None)` | Formats exception or log-record details for Telegram. |
| `send_to_log_errors(text)` | Sends a prepared message to the error destination. |
| `report_exc(exc, context=None)` | Reports an exception. |
| `report_record(record)` | Reports a logging record. |

The reporter classifies expected Telegram errors, trims long tracebacks, escapes HTML, and avoids raising if the destination is not configured.

`__main__.py` wires error reporting in two places:

1. PTB error handler for handler exceptions.
2. Asyncio loop exception handler for background task failures.

## `timedate_format.py`

This module is the single source of truth for UTC datetime handling.

| Function | Use |
|---|---|
| `utc_now()` | Store timestamps and compare elapsed time. |
| `to_utc(dt)` | Normalize naive or aware datetimes before arithmetic. |
| `fmt_dt(dt)` | Display datetimes as `DD-MM-YYYY | HH:MM`. |
| `utc_now_str()` | Display the current UTC time using `fmt_dt()`. |

Do not call `datetime.utcnow()` or `datetime.now(timezone.utc)` outside this utility.

## Utility boundaries

- Keep generic runtime concerns in `utils/`.
- Keep feature-specific text and keyboard policy in `modules/helper/` or workflows.
- Use `fan_out()` rather than hand-written unbounded `asyncio.gather()` loops for Telegram API operations across groups.
- Use prefix helpers for all command filters so custom prefixes remain consistent.
