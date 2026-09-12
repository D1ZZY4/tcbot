# i18n Translation Catalog

User-facing strings live here as TOML, one directory per locale. Python
code looks strings up by stable semantic key and never embeds user-facing
wording for localized surfaces.

## Layout

```text
i18n/
├── en-US/              Source of truth. Must hold every key.
│   ├── common.toml     Shared generic errors and notices.
│   ├── button.toml     Every button label, never duplicated.
│   ├── language.toml   Language-preference flow strings plus its help prose.
│   ├── help.toml       Help index header for help.py itself.
│   └── <domain>.toml   One file per module (banning, kicking, appeals,
│                       ...): each holds that module's [help] tables.
├── id/                 Example future locale (partial is legal).
└── README.md           This file.
```

File name is the key prefix: `language.toml` holding `done = ...`
is addressed as `language.done`. Section tables (`[area]`) are allowed
inside a file and extend the prefix (`[x]` + `y` = `file.x.y`).

## Rules for translators

1. Never rename files or keys. Add missing keys by copying the `en-US`
   shape, never by inventing structure.
2. Placeholders (`{user}`, `{count}`, ...) are code. Keep the exact set
   the `en-US` entry documents; a mismatch fails tests. Bare names only:
   no format specs (`{n:03d}`) and no conversions (`{x!r}`).
3. Write raw text, never backslashes: the engine escapes MarkdownV2 at
   render time, so `Done.` stays `Done.` in TOML (use literal single
   quotes to keep it obvious; basic double quotes work too).
4. `{placeholder}` values arrive pre-formatted from code: `mention()`
   style fragments pass through, raw text is escaped. Do not add `*`,
   `_`, `` ` ``, `[`, `]`, `(`, `)` around a placeholder unless the
   `en-US` entry does.
5. Newlines are `\n` inside basic strings, literal line breaks are not
   allowed; keep messages to the same paragraph breaks as `en-US`.
6. Mini-markup only: `` `code` `` and `*bold*` spans, balanced and
   unnested, with no braces inside. Anything else (including a lone
   `*` or backtick) fails tests. Close multi-line `"""` blocks tight
   against the last content line so no trailing newline ships.

## Help prose

Help content lives per domain (`banning.toml` holds `[help]` tables
for the ban module, `help.toml` holds the help index header). Only prose
moves: section order and dynamic values stay in Python, which composes
them via the stable keys (`banning.help.overview`,
`banning.help.what.body`, ...). Migrate one domain at a time; never
leave prose duplicated between TOML and Python.

Section labels and scope bodies are shared (`common.toml` `[section]`,
`[context]`, `[target]`): labels render raw (plain buttons show them
verbatim, section titles escape them via `bold()`), bodies render
MarkdownV2. `who_section` / `where_section` / `target_section` take the
locale alongside the body.

Every module exposes `get_help(locale)` returning its `HelpEntry`;
`__help__` stays as the default-locale entry for tests and fallbacks.
`help.py` rebuilds content per request via `_builder_help(locale)`, so
topics, overviews, sections, and keyboards all follow the tapper's
locale. Module display names stay English identifiers.

## Runtime strings

Command replies, prompts, and result lines migrate the same way: prose
in TOML, structure in Python. Handlers resolve the render locale once
via `helper.locale.locale_for_update(update)`: private chats use the
sender's personal locale, groups use the group locale, so a shared
audience always reads one language. Direct messages to one user resolve
via `locale_for_user`; event handlers without an update use
`locale_for_chat`. Every `t()` call passes that locale explicitly; the
default locale is only for tests and goldens.

Each key documents its send path. Keys sent without `parse_mode` must
render with `plain=True` (Telegram never parses them, so escaped text
would show raw backslashes). Keys sent as MarkdownV2 use the default
mode. Dynamics cross as raw data or `Safe` pre-formatted markup, never
pre-escaped.

## Adding a locale

1. Copy `en-US/` to `<locale>/` (BCP 47 shape, e.g. `id`, `pt-BR`).
2. Set `button.language_name` to the locale display name.
3. Translate values. Partial files are legal: missing keys fall back
   to `en-US` per key at runtime. Button labels render as plain text;
   message templates are escaped by the engine, so translators never
   write backslashes in either file.
4. Run `uv run --with pytest pytest tests/test_i18n.py -q`: placeholder
   mismatches and MarkdownV2 violations fail the suite.

## Adding a domain

Create `<locale>/<domain>.toml` in `en-US/` first with every key the
feature needs, then mirror the file (even empty of translations) in
other locales only when translating it. Document new keys with a
`# Placeholders:` comment when non-obvious.

## What stays out

Audit logs, staff operational messages, and infra error reports stay
English in code. Only end-user surfaces move here, one feature at a
time; do not migrate unrelated strings in a translation commit.
