# Runtime utilities

This page documents `tcbot/utils/`, the cross-cutting runtime layer. These
modules own behavior that is shared by handlers, flows, workers, and the
application lifecycle. They do not own domain rules.

## Modules

| Module | Responsibility |
|---|---|
| `i18n.py` | TOML catalog loading, `t()`, locale resolution, and rich markup helpers. |
| `dispatch.py` | `fan_out`, `gather_bounded`, bounded fan-out, and error classification. |
| `circuit_breaker.py` | `CLOSED`, `OPEN`, and `HALF_OPEN` breakers for Telegram and PostgreSQL. |
| `transport.py` | Shared HTTP and Telegram timeouts plus the API pool size. |
| `time_and_date.py` | UTC storage, formatting, duration parsing, and measurement. |
| `prefixes.py` | Command filter construction for all configured prefixes. |
| `logger.py` | Loguru-backed logging setup bridged to the standard library. |
| `error_reporter.py` is at package root | Error classification, scrubbing, dedup, and shipping. |
| `metrics.py` | Runtime metric counters. |
| `tasks.py` | `TaskTracker` for supervised background tasks. |
| `update_processor.py` | Keyed update serialization for PTB. |
| `pagination.py` | Page arithmetic for paged views. |
| `secrets.py` | Constant-time comparison for inbound credentials. |

## Internationalization

`utils/i18n.py` loads every `i18n/<locale>/*.toml` catalog and flattens it into
dotted keys. `en-US` is the source of truth; missing keys fall back per key.
The `id` alias resolves to `id-ID` for stored preferences and in-flight
callbacks.

`t(key, locale, **values)` substitutes keyword placeholders only. In rich
mode, literal text is HTML-escaped and the backtick code and asterisk bold
mini-markup spans become `<code>` and `<b>` tags. `plain=True` keeps raw text
for callback alerts that Telegram never parses. `Safe` marks preformatted
fragments from formatting helpers so they pass through verbatim.

`resolve_locale()` applies explicit precedence, then the user locale in
private chats or the group locale in groups, then the community default, then
`en-US`. Resolution never raises. See
[language](../features/language.md) and
[transport](../pipelines/transport.md).

## Bounded dispatch and breakers

`fan_out(coros, max_concurrent=10)` runs Telegram calls concurrently under a
semaphore and integrates the Telegram breaker. While the circuit is `OPEN`, a
slot is skipped with `CircuitOpenError` instead of firing a call that would
time out. A `BadRequest` is a service refusal and does not count as a failure;
`TimedOut`, `NetworkError`, and builtin `TimeoutError` do. Cancellation always
propagates. `gather_bounded()` provides the same concurrency bound for pure
database bursts without breaker interaction.

Both breakers use `failure_threshold = 5` and `recovery_timeout = 60` seconds.
`HALF_OPEN` admits a single probe. See
[rate limiting](../pipelines/ratelimit.md) and
[performance](../operations/performance.md).

## Time and transport budgets

`time_and_date.py` owns `utc_now()`, `to_utc()`, `fmt_dt()`, `utc_now_str()`,
`parse_duration()`, `fmt_duration()`, and monotonic measurement. All database
timestamps are stored in UTC, and naive values are assumed UTC before
arithmetic. `parse_duration()` accepts `s`, `m`, `h`, `d`, `w`, `mo`, and `ye`
suffixes with a 100-year cap.

`transport.py` owns `HTTP_READ_TIMEOUT = 60`, `HTTP_WRITE_TIMEOUT = 30`,
`HTTP_CONNECT_TIMEOUT = 30`, `HTTP_POOL_TIMEOUT = 15`,
`TELEGRAM_LOOKUP_TIMEOUT = 3.0`, `TELEGRAM_ACTION_TIMEOUT = 20.0`, and
`API_POOL_SIZE = 16`.

## Prefixes and commands

`prefixes.py` builds PTB filters for every configured prefix and handles
longest-prefix-first matching plus optional `@botname` suffixes.
`build_prefixed_filters("tcban")` is the standard command entry filter;
`parse_cmd_args()` extracts arguments from the matched message text.
`ALL_PREFIXES_CMD_FILTER` is used in conversation escape filters.

## Logging, error reporting, and tasks

`logger.py` installs a Loguru-backed shim bridged to the standard library so
caplog and the Telegram error handler see records. Use a module logger rather
than `print()`.

`error_reporter.py` classifies exceptions, suppresses benign and transient
ones, scrubs credential-shaped text, fingerprints and deduplicates incidents,
and ships reports to the configured error destination, falling back to the
Owner DM. Shipping is capped at 20 reports per 60 seconds and a suppressed
count is folded into a summary. Sentry is opt-in through `SENTRY_DSN`.

`TaskTracker` supervises fire-and-forget tasks and exposes a `drain()` method
used by the shutdown sequence. `KeyedUpdateProcessor` serializes updates per
`(chat, user)` so a ConversationHandler sees one update at a time without
blocking the rest of the federation.

## Validation hints

- `tests/test_time_and_date.py`, `tests/test_prefixes.py`, and
  `tests/test_dispatch.py` cover the deterministic helpers.
- `tests/test_circuit_breaker.py`, `tests/test_error_reporter_*.py`, and
  `tests/test_update_processor.py` cover runtime behavior.
- `tests/test_i18n.py` and `tests/test_formatter.py` pin catalog and markup
  contracts.
