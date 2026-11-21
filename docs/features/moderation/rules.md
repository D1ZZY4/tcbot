# Community rules

## Purpose and ownership

Community rules let staff maintain one canonical rule set inside the bot and
publish it to the main channel. The database is the source of truth; the
channel is a representation that a later publish reconciles. The feature owns
four surfaces: the staff editor, the channel representation, the moderation
picker, and member acknowledgement.

- `tcbot/modules/rules.py`: `/tcrules`, `/rules`, and callback registration.
- `tcbot/modules/helper/pipelines/rules_flow.py`: editor conversation.
- `tcbot/modules/helper/pipelines/rules_publish.py`: publish and channel sync.
- `tcbot/database/rules_db/`: set, draft, category, item, publication, run,
  and acknowledgement helpers.
- `tcbot/modules/helper/messages/rules.py`: channel and menu renderers.
- `i18n/<locale>/rules.toml`: editor, picker, publish, and acknowledgement text.

## Configuration

`MAIN_CHANNEL` is the numeric chat id of the main channel and the publication
target. It must be negative; a positive value is treated as unset. When it is
empty, a draft can still be edited but publish refuses with a clear message.
The bot needs `can_post_messages`, `can_edit_messages`, and, when a category
or part is removed, `can_delete_messages`.

The community menu links are derived from `MAIN_CHANNEL`, `MAIN_GROUP`,
`LOGS`, and `APPEALS` through `tcbot/utils/community_links.py`. A chat username
wins, otherwise its invite link is used; a chat with neither drops its button.
The former `COMMUNITY_*_URL` variables are gone.

## Staff flow

`/tcrules` requires `rules.manage`. In a group it replies with a prompt to use
the command in private chat so the panel does not flood the group. The panel
shows the set, the current published version, the draft state, and the channel
slot counts. The editor supports adding and renaming categories, adding items
with a title, plain-text body, and optional http(s) reference URL, previewing
the rendered channel text, publishing, and discarding the draft.

A draft is cloned from the current published version. The clone snapshots the
category titles and orders, so renaming or reordering categories later cannot
change an older published version. Only one draft per set and locale can exist
at a time. Publishing supersedes the previous published version and requires
at least one item.

A new community set starts with a small default catalogue (Conduct, Spam and
Advertising, Content, Safety, Other). These are editable content, not fixed
policy: staff can rename, reorder, retire, and add categories.

## Publish and channel sync

Publish first acquires a short-lived run for the set and channel; a live run
refuses a second concurrent publish. The database transition commits before
Telegram is touched. Each rendered part becomes one channel message identified
by its stored message id. A part whose content hash is unchanged is edited in
place; a new part is sent, and an unused part is retired. A failed channel
operation is recorded on its slot and reported to staff; the next publish
reconciles it. There is no sync command, rebuild command, or background retry.

Because Telegram edits cannot move an already-sent message, reordering
categories does not move old channel messages. The first published order is
stable and new categories append at the end. A crash between Telegram send and
the message-id write can produce a duplicate on the next publish; exactly-once
delivery is not promised.

## Moderation picker

The shared step in `rules_step.py` renders published items as a multi-select
picker. A flow keeps the chosen item ids and an optional "Other / Not covered"
note in its conversation scope and passes them to the decision writer, which
attaches them to the case through `moderation_db.link_case_rules` in the same
transaction as the decision. Draft items are refused by the schema; items from
a superseded version remain linkable so a publish during a flow cannot break
the action. When no rules are published the step is skipped so moderation is
never blocked.

The linked rule titles are also shown on `/check` ban details and on the staff
appeal review card, so a reviewer sees the exact rules the case cited rather
than a newer version's wording. A changelog entry records the change.

## Federation origin of the main group

The main group, main channel, proof archive, and the log and appeal
destinations are deployment infrastructure. They are never connected through
`/tcconnect` or the bot-added flow, even when one of them is a group. The main
group is still a valid origin for moderation commands: the origin gate
accepts `MAIN_GROUP` as the primary group without reading connection state.
`MAIN_CHANNEL` must be a negative chat id.

## Member acknowledgement

The `I agree` button appears only on the greeting of a new member in the
primary group. It carries the version id and the member id; the handler refuses
a tap from another member, a stale version, a disabled flag, or a duplicate,
and answers exactly once. Acknowledgements are per published version and are
retained as history. A member who misses the greeting cannot acknowledge until
joining again; there is no DM prompt or automatic retry.

## Limitations

- Published content is en-US. Button and navigation labels follow the viewer.
- Rules bodies are plain text; no raw Markdown is accepted from staff.
- Acknowledgement is greeting-only, so the recorded count is a lower bound of
  actual acceptance, not a percentage of the community.
- Channel message order is fixed at first publish.
