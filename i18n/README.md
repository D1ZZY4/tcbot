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
│   ├── language.toml   Language-preference flow strings.
│   └── ban.toml        Ban help prose ([help] tables).
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

Help content moves per domain (`ban.toml` holds `[help]` tables for
the ban module). Only prose moves: section order, labels, and dynamic
values stay in Python, which composes them via the stable keys
(`ban.help.overview`, `ban.help.what.body`, ...). Migrate one domain
at a time; never leave prose duplicated between TOML and Python.

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
