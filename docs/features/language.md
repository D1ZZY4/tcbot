# Language

This page describes locale selection and the translation catalog. The
resolution tiers and rendering rules are implemented in `utils/i18n.py`,
`modules/helper/locale.py`, `modules/helper/settings_db` access, and
`tcbot/modules/language.py`.

Related pages: [helpers](../architecture/helpers.md),
[utilities](../architecture/utilities.md), and
[transport](../pipelines/transport.md).

## Purpose and ownership

Every user-facing message renders in a resolved locale. Locale preferences can
be set per user and per group, and a community default is available. User
wording lives in TOML files under `i18n/<locale>/`, with `en-US` as the source
of truth. Python code holds structure and stable keys, not prose.

Ownership: `utils/i18n.py` loads catalogs and renders templates;
`helper/locale.py` resolves a locale for one update; `database/settings_db.py`
persists preferences; `modules/language.py` owns the command and callbacks;
`buttons/language.py` builds the keyboards.

## Catalog structure

```text
i18n/
├── en-US/            Source of truth, must hold every key.
│   ├── common.toml   Shared notices and section labels.
│   ├── button.toml   Every button label, never duplicated.
│   ├── language.toml Language flow strings.
│   ├── help.toml     Help index header.
│   └── <domain>.toml One file per feature.
├── id-ID/            Indonesian catalog.
└── README.md         Translator contract.
```

The file name is the key prefix: `banning.toml` holding `done` registers
`banning.done`. Section tables extend the prefix. The `id` code still resolves
to `id-ID` for stored preferences and in-flight callbacks; new saves use
`id-ID`.

## Locale resolution

`locale_for_update(update)` resolves once per handler:

| Context | Source |
|---|---|
| Private chat | The sender's locale. |
| Group | The group locale, so a shared audience reads one language. |
| Direct message to one user | `locale_for_user`. |
| Event without update | `locale_for_chat`. |

`resolve_locale()` applies explicit precedence first, then the context locale,
then the community default, then `en-US`. Unknown or absent values fall
through, and resolution never raises. Every `t()` call passes the resolved
locale explicitly. The default is for tests and golden checks, not as a
shortcut in handlers.

Flows carry the moderator locale in conversation state using `{action}_locale`
keys, and a direct message to the target resolves that target's locale freshly.

## Templates and rendering

Templates are stored raw. In rich mode, literal text is HTML-escaped and the
backtick code and asterisk bold mini-markup spans become `<code>` and `<b>`
tags. Placeholders must be bare names such as `{user}` and `{count}`, with no
format specifications or conversions, and mini-markup spans must be balanced,
unnested, and free of braces.

`Safe` marks preformatted fragments from helpers such as `user_ref()`,
`code()`, and `bold()` so `t()` inserts them verbatim. Raw data is escaped.
`plain=True` keeps raw text for callback alerts, which Telegram never parses.
A rendering-mode mismatch shows raw escape characters or breaks parsing, so
keys document their send path.

## Command and callbacks

| Command | Alias | Access |
|---|---|---|
| `/language` | `/lang`, `/langs` | Anyone. Personal scope in PM, group scope in groups. |

| Callback | Effect |
|---|---|
| `language_menu` | Open the personal language panel from the start menu. |
| `lang:list:(user\|group)` | Re-render the option list. |
| `lang:set:(user\|group):<code>` | Save the locale and show a confirmation. |

Changing the group scope requires `can_manage_group(..., fresh=True)` and a
connected group. Group preference writes use `groups_db.set_group_locale()`;
personal writes use `settings_db.set_user_locale()`. Both cache layers are
invalidated so the change reaches every process. Alerts render in the
tapper's current locale, not the target locale, because the target may be
unknown or denied.

## Help content

Each module exposes `get_help(locale)` returning a `HelpEntry`. `__help__` is
the default-locale entry for tests and fallbacks. `help.py` rebuilds topics,
overviews, sections, and keyboards per request. Section labels and scope bodies
are shared through `common.toml` tables; labels render as plain text and bodies
render as rich markup. Module display names stay English identifiers.

## Edge cases

- A missing key falls back to `en-US` per key; a key missing everywhere logs an
  error and renders as a bracketed key.
- A stale locale in a callback is checked against the actual scope and refused.
- A locale change in one process reaches the others through the Redis L2 cache.

## Validation hints

`tests/test_i18n.py` checks placeholder sets and markup balance, and
`tests/test_keyboard_locale_contract.py` checks button labels.

```bash
uv run pytest tests/ -q -k i18n
```
