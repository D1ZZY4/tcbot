# Community rules

This page describes the rules editor, publication, member acknowledgment, and
the shared moderation picker. The draft model, publication sequence, and
acknowledgment path are drawn in [the rules diagram](../../pipelines/rules.md).

Related pages: [banning](banning.md), [language](../language.md), and
[the database layer](../../architecture/database.md).

## Purpose and ownership

A rule set owns categories and immutable published versions. Staff edit a
draft in the bot DM, publish it to the main channel, and members can
acknowledge a version in the welcome message. Moderation flows can cite
published rules through a shared picker.

Ownership: `rules.py` owns the commands and read-only callbacks;
`rules_flow.py` owns the editor conversation; `rules_publish.py` owns channel
publication; `rules_db/` owns drafts, items, versions, publications, and
acknowledgments; `greeting.py` owns the welcome-time ack button.

## Commands and access

| Command | Alias | Access | Scope |
|---|---|---|---|
| `/tcrules` | none | Staff with `rules.manage` | Private chat only. |
| `/rules` | none | Anyone | Private chat only. |

`/tcrules` uses `ratelimiter(THROTTLE_STAFF)` and `permission_only("rules.manage")`.
`/rules` uses `ratelimiter(THROTTLE_READ)`. Both refuse group contexts and ask
the user to open the bot DM.

## Editor conversation

The single entry is the `rules_edit_draft` callback. Five states cover three
text inputs, a URL input, and a discard confirmation:

| State | Value | Input |
|---|---|---|
| `WAITING_CATEGORY_TITLE` | 1 | Category title. |
| `WAITING_ITEM_TITLE` | 2 | Item title. |
| `WAITING_ITEM_BODY` | 3 | Item body. |
| `WAITING_ITEM_URL` | 4 | URL or empty. |
| `WAITING_CONFIRM_DISCARD` | 5 | Discard yes or no. |

Limits are title 200, body 3500, and URL 500 characters; URLs must start with
`https://` or `http://`. Category slugs match `^[a-z0-9][a-z0-9._-]*$` and are
capped at 40 characters so callbacks stay within Telegram's 64-byte limit.
`editor_allowed()` rechecks `rules.manage` on every editor surface and fails
closed.

Editor callbacks include `rules_edit_draft`, `rules_preview`, `rules_publish`,
`rules_discard`, `rules_discard_yes`, `rules_discard_no`, `rules_cat:<key>`,
`rules_cat_(rename|up|down|del):<key>`, `rules_cat_add`, `rules_item:<id>`,
`rules_item_add`, `rules_categories`, `rules_panel`, and the fallback
`rules_step:cancel`. The read-only menu uses `rules_menu`, `rules_page:<n>`,
and `rules_show:<key>`.

## Publication

`publish_rules()` runs under a database lease. `runs.reclaim_expired()` marks
stale running rows after a 300-second lease, then `runs.acquire()` inserts a
running row guarded by a partial unique index; a concurrent publish fails
immediately. `MAIN_CHANNEL` must be configured or publication is refused.

The channel text is split into parts of at most 4000 UTF-16 units, grouped by
category with a version and timestamp footer. Each part is hashed with SHA-256
and stored on its slot. A slot with a matching message id and hash is edited in
place; a changed or missing message is sent fresh. `mark_failed(missing=True)`
clears a stale id. Run states are `running`, `completed`, `partial`, and
`failed`; slot states are `pending`, `synced`, `missing`, `failed`, and
`retired`.

## Acknowledgment and picker

`greeting.py` attaches an "I agree" button in the primary group when the
published set requires acknowledgment and the member has not accepted that
exact version. The callback is `rules_ack:<version>:<member>`; `_acknowledge()`
verifies the tapper, the current version, the enabled flag, and the absence of
a prior record. The insert is `ON CONFLICT DO NOTHING`, so duplicate taps are
safe. A rules read failure never blocks the welcome.

The shared picker in `rules_step.py` uses `rules_step:pick:<id>`, `done`,
`other`, `clear`, and `cancel`. Ban has a dedicated step with
`WAITING_BAN_RULES` (2) and `WAITING_BAN_RULES_NOTE` (3); kick, mute, and warn
share the generic step. Selections are linked to the case through
`moderation_db.link_case_rules()`.

## Database impact

Drafts and published data live in `rule_sets`, `rule_versions`,
`rule_categories`, `rule_items`, `rule_publication_runs`, `rule_publications`,
and `rule_acknowledgements`. Published versions are immutable; every mutation
touches a draft. Publication commits to the database before touching Telegram.

## Logging

Category views render as rich tables where supported. `rules.publish.result`
reports synced and failed slot counts. Editor authorization failures and
publication errors are logged with the set id and operator id.

## Edge cases

- A crashed publish is reclaimed by the lease and reconciled by the next run.
- A deleted channel post is treated as missing and re-sent.
- A rules read failure in the greeting path sends the welcome without a button.
- A stale acknowledgment tap is refused with a localized alert.

## Validation hints

Relevant tests include `tests/test_rules_*.py` and
`tests/test_keyboard_locale_contract.py`.

```bash
uv run pytest tests/ -q -k rules
```
