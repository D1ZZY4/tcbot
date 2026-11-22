# Modules

This page describes how Telegram command modules are discovered, filtered, and
registered, and which module owns each command. It covers the `tcbot/modules/`
layer only. Shared code lives in [the helper package](helpers.md), and the
conversation flow implementations are drawn in [the pipelines](../pipelines/banning.md).

## Module discovery and registration

`tcbot/modules/__init__.py` is the single owner of module discovery. It finds
every `*.py` file in `tcbot/modules/` except `__init__.py`, plus every
subdirectory with an `__init__.py` except `helper` and `__pycache__`. Names are
sorted so registration order is deterministic across filesystems.

`MODULES_LOAD` and `MODULES_NO_LOAD` are applied here. Both lists are validated
against the discovered set; an invalid name exits startup with an error. When
`MODULES_LOAD` is set it acts as an allowlist, and `MODULES_NO_LOAD` then
removes names from the result.

`get_handlers()` imports every active module and collects its `__handlers__`
list. Imports run first so all failures are reported together; collection then
follows the same sorted order. Each module exposes its handlers as
`__handlers__`, a list of PTB handler objects.

`register_handlers()` in `tcbot/__main__.py` attaches, in order:

1. The global rate-limit `TypeHandler(Update, global_rate_limit_handler)` at
   handler group `-1`.
2. The collected module handlers.
3. The member-cache harvester at group `10`.
4. The application error handler.

## Handler anatomy

Handlers are small orchestration functions. A typical command handler:

- guards `effective_message`, `effective_user`, and `effective_chat`;
- resolves the locale once with `helper.locale.locale_for_update`;
- delegates authorization to decorators and guards;
- delegates persistence to `tcbot/database/*_db.py` helpers;
- delegates multi-step work to a flow in `helper/pipelines/`;
- sends replies through `messages/reply_rich`.

Decorator order is fixed: `ratelimiter()` outermost, the required
authorization guard second, and `log_execution` innermost. Message-event
handlers are exempt from per-handler rate limits. Callback-query handlers
answer the query before visible work.

## Command ownership

Commands are matched by `build_prefixed_filters()` against all configured
prefixes (`/`, `!`, and `.` by default). Short aliases are intentional.

| Module | Commands | Access |
|---|---|---|
| `bans.py` | `/tcban`, `/tcb` | Developer and above. |
| `unban.py` | `/tcunban`, `/tcunb` | Developer and above. |
| `kick.py` | `/tckick`, `/tck` | Moderator and above. |
| `mute.py` | `/tcmute`, `/tcm`, `/tcunmute`, `/tcunm`, `/tcum` | Moderator and above. |
| `warns.py` | `/tcwarn`, `/tcw`, `/tcunwarn`, `/tcunw`, `/warns`, `/warnlist`, `/resetwarns`, `/clearwarns` | Moderator and above. |
| `check.py` | `/check`, `/c`, `/checkme`, `/cme` | Anyone. |
| `appeals.py` | `/start appeal_<ref>` deep link, `#appeal` in the main group, `appeal_approve_*`, `appeal_reject_*` | Banned member or staff. |
| `connect.py` | `/tcconnect`, `/tccon`, plus `MY_CHAT_MEMBER` events | Group admins and the bot-added flow. |
| `disconnecting.py` | `/tcdisconnect`, `/rmtc` | Group creator or federation staff. |
| `groups.py` | `/tcgroups`, `/tcg` | Anyone. |
| `rules.py` | `/tcrules`, `/rules`, rule callbacks | Staff editor and public reader. |
| `admins.py` | `/tcpromote`, `/tcp`, `/tcdemote`, `/tcd`, `/transferowner`, `/tfowner`, `/tcpromoterequests`, `/tcreqs`, `/tcpromotelist`, `/tcplist`, promotion callbacks | Staff and Owner. |
| `language.py` | `/language`, `/lang`, `/langs`, language callbacks | Anyone; group scope requires manage rights. |
| `stats.py` | `/tcstats`, `/tcs`, stats callbacks | Anyone; drill-downs check rank. |
| `start.py` | `/start`, main-menu callbacks | Anyone. |
| `help.py` | `/help`, help callbacks | Anyone. |
| `about.py` | `about_menu` callback | Anyone. |
| `additional.py` | `additional_menu` callback | Anyone. |
| `privacy.py` | privacy callbacks | Anyone. |
| `greeting.py` | New-member, join-request, left-member, and migration events | Event driven. |
| `broadcast.py` | `/tcbroadcast`, `/bc` | Staff. |
| `maintenance.py` | `/tcleaveall`, `/leaveall`, `/exitall`, `/cleanup`, `/tcclean`, `/tcc`, `/tcforget`, `/tcf`, `/tcrepair`, `/tcr` | Staff and Owner. |
| `netspeed.py` | `/ping`, `/p`, `/speedtest`, `/st` | Owner. |

## Help entries

Modules that describe themselves expose `get_help(locale)` returning a
`HelpEntry`. `__help__` remains the default-locale entry for tests and
fallbacks. `help.py` rebuilds topics, overviews, sections, and keyboards per
request so the help follows the tapper's locale. Panel-only modules such as
`about`, `additional`, `privacy`, and `start` set `__module_name__ = None` and
do not expose a help entry.

Both `en-US` wording and other locales live in `i18n/<locale>/*.toml`; Python
holds structure and stable keys, not user-facing prose.

## Authorization layers

Two layers are both required and neither substitutes for the other:

- Decorators answer "may this user run this command at all": `owner_only`,
  `staff_only`, `mod_only`, `basic_mod_only`, and `permission_only(key)`.
- Guards in `helper/guards.py` answer "may this executor act on this specific
  target": `resolve_and_check`, `classify_and_check`, `enforcement_refusal`,
  and the demote gates.

All fresh role reads fail closed: a lookup error refuses the action. See
[permissions](../pipelines/permissions.md).

## Module boundaries and dead paths

- Feature modules must not build SQLAlchemy statements or write to the
  database directly.
- Keyboard builders belong only in `helper/buttons/`.
- Conversation flows belong only in `helper/pipelines/*_flow.py`.
- Message formatting belongs only in `helper/messages/` and `utils/i18n.py`.
- There is no separate MarkdownV2 fallback send path. The rich transport
  keeps the inline keyboard as a fallback only where a button cell cannot be
  converted to a rich button.

## Validation hints

Check that a new module exposes `__handlers__`, that it is not named `helper`,
and that `get_help` returns localized content. `tests/test_layering.py` guards
import boundaries, and `tests/test_keyboard_locale_contract.py` checks that
button labels come from the catalog.
