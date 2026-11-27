# Language

Every user-facing message renders in a resolved locale. Preferences can be set
per user and per group, and a community default is available. Wording lives in
TOML files under `i18n/<locale>/`, with `en-US` as the source of truth. Python
holds structure and stable keys, not prose.

## Ownership

- `utils/i18n.py` loads catalogs and renders templates.
- `modules/helper/locale.py` resolves a locale for one update.
- `database/settings_db.py` and `database/groups_db.py` persist preferences.
- `modules/language.py` owns the command and callbacks.
- `buttons/language.py` builds the keyboards.

## Catalog structure

```text
i18n/
├── en-US/            Source of truth, must hold every key.
│   ├── common.toml   Shared notices and section labels.
│   ├── button.toml   Every button label, never duplicated.
│   ├── language.toml Language flow strings.
│   ├── help.toml     Help index, module, and section titles plus guidance.
│   └── <domain>.toml One file per feature.
├── id-ID/            Indonesian catalog.
└── README.md         Translator contract.
```

The file name is the key prefix: `banning.toml` holding `done` registers
`banning.done`. Section tables extend the prefix. The `id` code still resolves
to `id-ID` for stored preferences and in-flight callbacks; new saves use
`id-ID`.

## Locale resolution

`locale_for_update(ctx)` resolves once per handler:

| Context | Source |
|---|---|
| Private chat | The sender's locale. |
| Group | The group locale, so a shared audience reads one language. |
| Direct message to one user | `locale_for_user`. |
| Event without update | `locale_for_chat`. |

`resolve_locale()` applies explicit precedence, then the context locale, then
the community default, then `en-US`. Unknown or absent values fall through,
and resolution never raises. Every `t()` call passes the resolved locale
explicitly. Flows carry the moderator locale in conversation state using
`{action}_locale` keys; a direct message to a target resolves that target's
locale freshly.

## Templates and rendering

Templates are stored raw. In rich mode literal text is HTML-escaped and the
backtick code, asterisk bold, and tilde italic mini-markup spans become `<code>`,
`<b>`, and `<i>`. Placeholders must be bare names such as `{user}` and
`{count}`, with no format specifications or conversions. Mini-markup spans must
be balanced, unnested, and free of braces. `Safe` marks preformatted fragments
from `user_ref()`, `code()`, and `bold()` so `t()` inserts them verbatim.

`plain=True` keeps raw text for callback alerts, which Telegram never parses.
A rendering-mode mismatch shows raw escape characters or breaks parsing, so
each key documents its send path in the catalog.

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
connected group, the primary group, or a deployment-owned destination. Group
writes use `groups_db.set_group_locale()`; personal
writes use `settings_db.set_user_locale()`. Both invalidate every cache layer
so the change reaches other processes through Redis L2. Alerts render in the
tapper's current locale, not the target locale, because the target may be
unknown or denied.

## Help content

Each module exposes `get_help(locale)` returning a `HelpEntry`. `__help__` is
the default-locale entry for tests and fallbacks. `help.py` rebuilds topics,
overviews, sections, and keyboards per request. Section labels and scope bodies
are shared through `common.toml` tables; labels render as plain text and bodies
as rich markup. Module display names stay English identifiers.

## Edge cases

- Every locale must define every key; catalog parity is enforced by the test
  suite. A key missing everywhere logs an error and renders as a bracketed key.
- A stale locale in a callback is checked against the actual scope and refused.
- A locale change in one process reaches the others through the Redis L2 cache.

## Validation

```bash
uv run pytest tests/ -q -k i18n
```

`tests/test_i18n.py` checks placeholder sets and markup balance, and
`tests/test_keyboard_locale_contract.py` checks button labels.
