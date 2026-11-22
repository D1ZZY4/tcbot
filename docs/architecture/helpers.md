# Helper package

This page documents `tcbot/modules/helper/`, the shared code used by every
command module. The helper package owns authorization helpers, extraction,
conversation flows, buttons, and message rendering. It never registers
handlers itself; the owning module does that through `__handlers__`. For the
flows drawn as diagrams, see [the pipelines](../pipelines/banning.md).

## Layout

| Path | Responsibility |
|---|---|
| `decorators/` | Rate-limit and authorization decorators plus execution logging. |
| `guards.py` | Executor-versus-target checks and the demote gates. |
| `identity.py` | Self, bot, Telegram, Owner, and staff classification. |
| `targets.py` | Validation entry points shared by command handlers. |
| `extraction/` | Target resolution from replies, IDs, usernames, and mentions. |
| `locale.py` | Locale resolution for one update. |
| `scope.py` | Per-conversation payload scope keyed by chat and user. |
| `ban_info.py` | Shared ban detail and summary builders. |
| `replies` via `messages/replies.py` | Localized reply helpers and the `HelpEntry` shape. |
| `pipelines/` | ConversationHandler factories and their step implementations. |
| `buttons/` | All inline keyboard builders. |
| `messages/` | Rich transport, formatters, panels, links, and audit logs. |

## Decorators and guards

`decorators/auth.py` exposes `owner_only`, `staff_only` (`admin` and above),
`mod_only` (`developer` and above), `basic_mod_only` (`moderator` and above),
and `permission_only(key)`. `decorators/ratelimit.py` exposes `ratelimiter`,
the `Throttle` tiers, and `global_rate_limit_handler`. `decorators/tracing.py`
exposes `log_execution`.

`guards.py` owns `resolve_and_check`, `classify_and_check`,
`enforcement_verdict`, `enforcement_refusal`, `recheck_executor_rank`, the
callback rank checks, `outranks`, `can_demote_admin`, `banned_target_refusal`,
and `require_federation_origin`. Role lookups use `fresh=True` and fail closed.
The protected-target table lives in `identity.py` and is consulted through
`refuse_message` and `refuse_role`.

There are two demote policies. `demote_before_enforcement()` is best effort
for ban, kick, mute, and join enforcement because the moderation record
already exists. `demote_before_unban()` fails closed for manual unban and
appeal approval. See [permissions](../pipelines/permissions.md).

## Extraction and scope

`extract_target(update, args, bot, prefer_explicit=False)` resolves a target
in a fixed order: reply sender, explicit numeric ID or `@username`, partial
name only with `prefer_explicit=True`, then text-mention and `@mention`
entities. `extract_mod_target()` wraps it for moderation paths and reports
whether the first argument was consumed as the target. Bounded `get_chat`
lookups use the transport timeout and fall back to MTProto resolution.

`scope.flow_scope(ctx, update)` stores each flow's payload under
`conversation_key(update)` inside `ctx.user_data["tc_flow_scopes"]`. This keeps
simultaneous flows in different chats isolated. `callback_is_current()`
rejects taps from an older prompt message. See
[extraction and user data](../pipelines/extraction-user-data.md).

## Conversation pipelines

`pipelines/*_flow.py` modules own conversation state machines:

| Flow | Owner |
|---|---|
| Ban | `ban_flow.py` with `ban_confirmation.py`, `ban_rules_step.py`, `proof_session.py`. |
| Kick, mute, warn | `kick_flow.py`, `mute_flow.py`, `warn_flow.py` through `reason_flow.build_modaction_conv()`. |
| Unban | `unban_flow.py` plus the fail-closed gate in `demote_flow.py`. |
| Appeals | `appeal_submit_flow.py` and `appeal_review_flow.py`. |
| Rules | `rules_flow.py`, `rules_publish.py`, `rules_step.py`. |
| Roles | `promote_flow.py`, `promo_decision_flow.py`, `demote_flow.py`, `transfer_flow.py`. |
| Check and stats | `check_flow.py`, `stats_flow.py`. |
| Connection | `connected_flow.py`. |

Every flow has a cancellation fallback and uses `WAITING_*` state constants.
The exhaustive state and callback registry is in
[callbacks](../pipelines/callbacks.md).

## Buttons

Every inline keyboard builder lives in `buttons/`. The package re-exports the
public builders through `__init__.py` so existing dotted imports stay stable.
Builders take an explicit locale when their labels are localized and read
those labels from `button.toml`.

Buttons are rendered as rich buttons by `messages/rich_link.py`. The conversion
from a PTB inline keyboard is all-or-nothing: one cell that cannot map keeps
the whole keyboard inline as a fallback. See
[button styles](../reference/button-styles.md).

## Messages and rich transport

The `messages/` package owns every user-facing send and edit:

| Module | Responsibility |
|---|---|
| `rich_msg.py` | `html_message`, `blocks_message`, `send_rich`, `reply_rich`. |
| `rich_edit.py` | `edit_rich`, the safe edit helpers, callback answers, `send_log`. |
| `rich_text.py` | `style(text)`, which returns rich text unchanged. |
| `rich_style.py` | HTML escaping and bold, italic, underline, strike, spoiler. |
| `rich_format.py` | Headings, text, quotes, highlights, code, pre, footnotes, dividers. |
| `rich_list.py` | Lists and details blocks. |
| `rich_table.py` | Rich tables. |
| `rich_link.py` | Links, ID-based mentions, and every rich button feature. |
| `rich_media.py` | Photos, videos, slideshows, and collages. |
| `audit_logs.py` | `LogBuilder` and the federation log builders. |
| `links.py` | Telegram link builders and deep links. |
| `panels.py` | Shared information and profile panels. |
| `rules.py` | Rules rendering and hashing. |
| `replies.py` | Localized reply helpers and `HelpEntry`. |

`send_rich` and `edit_rich` call `bot.do_api_request` with a `rich_message`
payload. There is no parse mode selection anywhere in the application. The
`parse_mode` arguments on the safe helpers are accepted for call-site
compatibility and discarded. Direct PTB fallback calls exist only for
lightweight non-PTB objects in tests. See
[transport](../pipelines/transport.md).

## Logging

Use a module logger from `tcbot.utils.logger`. Log I/O failures with actionable
identifiers and without secrets or private chat contents. Federation log posts
go through `messages.audit_logs` builders and `send_log` to the configured
`LOGS` destination. Error reports go through `error_reporter.py`.

## Validation hints

- `tests/test_rich_modules.py` and `tests/test_rich.py` pin rich formatting.
- `tests/test_keyboards.py` and `tests/test_keyboard_locale_contract.py` cover buttons.
- `tests/test_flow_scope.py` and `tests/test_callback_freshness.py` cover scope.
- `tests/test_layering.py` guards module boundaries.
