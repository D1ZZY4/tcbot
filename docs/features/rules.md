# Community rules

A rule set owns categories and immutable published versions. Staff edit a draft
in the bot DM, publish it to the main channel, and members can acknowledge a
version in the welcome message. Moderation flows can cite published rules
through a shared picker. The full flow diagrams are in
[the rules flow](../flows/rules.md).

## Ownership

- `modules/rules.py` owns the `/tcrules` entry, the `/rules` menu, and their read callbacks.
- `modules/helper/pipelines/rules_editor.py` owns the editor conversation.
- `modules/helper/pipelines/rules_publish.py` owns channel publication.
- `database/rules_db/` owns drafts, items, versions, publications, and runs.
- `modules/greeting.py` owns the welcome-time acknowledgement button.

## Commands

| Command | Access | Scope |
|---|---|---|
| `/tcrules` (alias `/tcrls`) | Staff with `rules.manage` | Private chat only. |
| `/rules` | Anyone | Group or private chat. |

The editor refuses group contexts and asks the user to open the bot DM.
`editor_allowed()` rechecks `rules.manage` on every editor surface and fails
closed when the lookup fails. The read-only menu has no chat-type restriction.

## Public menu

`/rules` opens a topic index with two categories per row across pages of eight.
`rules_index:<page>`, `rules_prev:<page>`, `rules_next:<page>`, and `close_msg`
navigate the index, and a stale page index is clamped to the published set.
Tapping a category with `rules_show:<key>` renders its localized one-line
description and one button per section, where sections are derived from the
stored item titles. Tapping `rules_section:<index>` renders that section's rules.
The older `rules_menu` and `rules_page` callbacks stay registered so keyboards
emitted before the index redesign still open the current menu.

## Editor conversation

`build_rules_conv()` owns one interactive state for every panel callback and
text step, plus a second state for the discard confirmation.

| State | Value | Input |
|---|---|---|
| `WAITING_EDITOR_MENU` | 0 | Panel callback, category or item text step. |
| `WAITING_CONFIRM_DISCARD` | 5 | Discard yes or no. |

Limits are title 200, body 3500, and URL 500 characters; URLs must start with
`https://` or `http://`. Category slugs match `^[a-z0-9][a-z0-9._-]*$` and are
capped at 40 characters so the longest callback stays inside Telegram's 64-byte
limit. Typed answers are routed by the pending step stored in the conversation
scope, so every button and text prompt has a reachable handler.

## Publication

`publish_rules()` runs under a database lease, not a background retry loop. The
database commits first and Telegram is touched second. A failed channel
operation is recorded on its slot and reconciled by the next publish.

- `runs.reclaim_expired()` marks stale running rows after a 300-second lease.
- `runs.acquire()` inserts a running row guarded by a partial unique index; a
  concurrent publish fails immediately.
- `MAIN_CHANNEL` must be configured or publication is refused.
- Channel text is split into parts of at most 4000 UTF-16 units, grouped by
  category with a version and timestamp footer.
- Each part is hashed with SHA-256 and stored on its slot. A slot with an
  existing message is edited in place, including when its text changed. A slot
  without a message id, or a post that no longer exists, is sent fresh and the
  new id is recorded. A failed channel operation is marked on the slot.

Run states are `running`, `completed`, `partial`, and `failed`. Slot states are
`pending`, `synced`, `missing`, `failed`, and `retired`.

## Categories

A category groups one topic from the operator's rule documents. The seed script
creates one category per document stem, such as `cheat` or
`doxing-dan-privasi`. Localized labels and one-line descriptions are read from
`rule_category_content` (one row per category and locale when present), with the
stored category title as fallback; no automatic writer seeds those rows. The
public menu resolves them for the reader's locale with a working-default
fallback, so the rule set owns its own presentation and the translation catalog
no longer carries per-category wording.
A new community starts with the editable `mandatory` and `optional` defaults
until a seed or a staff edit replaces them, and the seed retires those two
buckets when it writes the topic categories. Staff can add, rename, reorder,
and retire categories from the editor. The moderation picker prefixes a
selection with the stored category title.

## Seeding from Markdown

`scripts/seed_rules.py` converts operator Markdown into the plain-text items
the bot stores. It reads `rules/*.md` by default and accepts `--rules-dir` for
another folder. Each `##` section becomes one item, the document H1 prefixes
each title, and inline Markdown is stripped so members never see literal
syntax. A section longer than the 3500-character body cap is an error rather
than a silent truncation.

```bash
uv run python scripts/seed_rules.py --dry-run
uv run python scripts/seed_rules.py --user-id 123456789
```

A dry run prints the parsed categories and item titles without writing to the
database. A real run opens a draft, replaces its items with the parsed set,
publishes it as one new version, and retires the superseded default buckets.
`--user-id` records the creator and publisher and defaults to `OWNER_ID`; the
database URL comes from `config.env`, `.env`, or the environment. Rule bodies
have one content locale, so the seed always publishes en-US.

## Acknowledgement

Acknowledgement is a greeting-only surface. In the primary group the bot
attaches an "I agree" button when a published version exists and the member has
not accepted that exact version. The `requires_acknowledgement` flag is no
longer consulted. A rules read failure never blocks the welcome: the greeting
is sent without a button.

The callback is `rules_ack:<version>:<member>`. `_acknowledge()` verifies the
tapping user is the named member, the version is still current, and no prior
record exists. The insert is `ON CONFLICT DO NOTHING`,
so duplicate taps are safe. Acknowledgement never appears on channel posts or
in the `/rules` menu.

## Shared picker

`rules_picker.py` provides action-agnostic helpers: `callback_for`,
`item_id_from_callback`, `toggle`, and `picker_text`. Flows store selected item
ids and an optional note in their scope, then link them to the case through
`moderation_db.link_case_rules()`. Ban has a dedicated picker step with
`WAITING_BAN_RULES` (2) and `WAITING_BAN_RULES_NOTE` (3); kick, mute, and warn
share the generic step. All four use the same callbacks: `rules_step:pick:<id>`,
`done`, `other`, `clear`, and `cancel`.

## Database impact

Drafts and published data live in `rule_sets`, `rule_set_versions`,
`rule_categories`, `rule_category_content`, `rule_items`,
`rule_publication_runs`, `rule_publications`, and `rule_acknowledgements`.
Published versions are immutable; every mutation touches a draft. Publication
commits to the database before touching Telegram.

## Validation

```bash
uv run pytest tests/ -q -k rules
```

Relevant tests include `tests/test_rules_*.py` and
`tests/test_keyboard_locale_contract.py`.
