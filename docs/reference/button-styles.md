# Button styles

This page is the reference for rich buttons and callback-data naming. All
keyboard builders live in `tcbot/modules/helper/buttons/`; the rendering layer
is `modules/helper/messages/rich_link.py`. For the send and edit path, see
[transport](../pipelines/transport.md).

## Rich buttons

A rich button is emitted as a `<tg-button>` tag inside a `<tg-button-row>`.
`rich_link.button()` accepts exactly one action type per button:

| Keyword | Action type | Notes |
|---|---|---|
| `data` | `callback_data` | Must be at most 64 bytes. |
| `url` | `url` | A public HTTPS link. |
| `copy` | `copy_text` | Copies text on tap. |
| `web_app` | `web_app` | Private chats only. |
| `login_url` | `login_url` | Optional forward text and write access. |
| `switch_inline_query` | `switch_inline_query` | Opens inline mode. |
| `switch_inline_query_current_chat` | `switch_inline_query_current_chat` | Current-chat variant. |
| `switch_inline_query_chosen_chat` | `switch_inline_query_chosen_chat` | With optional chat-type flags. |
| `disabled` | `disabled` | Inert button. |

Convenience wrappers such as `callback_button`, `url_button`, `copy_button`,
`web_app_button`, `login_button`, `switch_button`, and `disabled_button` are
thin aliases over `button()`.

## Styles and alignment

Friendly style names map to Bot API style values:

| Friendly name | API value |
|---|---|
| `default` | none |
| `blue` | `primary` |
| `green` | `success` |
| `red` | `danger` |
| `link` | `link` |

Raw API names `primary`, `success`, `danger`, and `link` are also accepted.
An unsupported style is dropped to no style, so an unknown value never emits
an invalid attribute.

Rows accept `align="left"`, `align="center"`, or `align="right"`. An unknown
alignment is ignored. At most eight buttons belong in one row. There is no
full-width attribute; a single-button row is the supported way to give a
button a whole row.

## Inline keyboard fallback

`keyboard_rows(reply_markup)` converts a PTB inline keyboard to rich rows. The
conversion is all-or-nothing: one cell that cannot map keeps the whole keyboard
inline. A cell fails to map when:

| Condition | Result |
|---|---|
| `callback_data` longer than 64 bytes | Whole keyboard stays inline. |
| A cell uses web app, login, switch-inline, copy-text, or disabled actions | No rich equivalent from a PTB cell, so it stays inline. |
| No string `text`, or neither callback data nor URL | No action to map. |
| The payload uses `blocks` instead of `html` | Buttons are not embedded. |

This is a transport fallback only. There is no separate MarkdownV2 parse-mode
send path in the application.

## Button label ownership

Every localized label lives exactly once in `i18n/<locale>/button.toml`.
Locale-dependent builders take an explicit `locale` argument. `help_topics_kb`
is locale-independent. A builder must never hardcode a user-facing label.

## Callback-data conventions

Callback payloads use colon-separated segments and stable prefixes. Dedicated
parsers in `messages/rich_edit.py` own the grammar:

| Parser | Rule |
|---|---|
| `callback_args(q, count)` | Exactly `count` segments; returns the tail or `None`. |
| `callback_args_optional(q, count)` | Allows one extra segment. |
| `callback_numbers(q, count)` | Parses the tail as integers. |

Common namespaces:

| Namespace | Owner | Purpose |
|---|---|---|
| `ban_*`, `kick_*`, `mute_*`, `warn_*` | Flow modules | Cancel, Done, Skip for each action. |
| `rules_step:*` | `rules_step.py`, `ban_rules_step.py` | Shared rules picker. |
| `appeal_approve_*`, `appeal_reject_*` | `appeals.py` | Review decisions. |
| `promo_approve:*`, `promo_reject:*`, `promo_role:*`, `demote_confirm:*` | `admins.py` | Role actions. |
| `check_*`, `checkme_*` | `check.py` | Profile drill-downs. |
| `stats_*` | `stats.py` | Statistics drill-downs. |
| `lang:*` | `language.py` | Locale selection. |
| `help*`, `about_menu`, `additional_menu`, `privacy_*` | Menu modules | Information panels. |
| `tc_join`, `tc_cancel` | `connected_flow.py` | Connection prompts. |

See the exhaustive registry in [callbacks](../pipelines/callbacks.md).

## Freshness and ownership

Moderation prompts record their message id in the flow scope and call
`scope.callback_is_current()` before acting. A tap from an older prompt is
answered and discarded. Action prompts carry an optional trailing executor
segment; a different tapper gets an alert and the prompt stays live.

## Links in buttons

`messages/links.py` owns link builders. `message_link()` produces
`https://t.me/c/<id>/<message_id>` with an optional thread parameter, and
`appeal_deep_link()` produces the bot DM deep link. A URL button is dropped
when its link is empty, so no dead button is sent. See
[transport](../pipelines/transport.md).

## Validation hints

Relevant tests include `tests/test_keyboards.py`,
`tests/test_keyboard_locale_contract.py`, `tests/test_rich_modules.py`, and
`tests/test_callback_freshness.py`.
