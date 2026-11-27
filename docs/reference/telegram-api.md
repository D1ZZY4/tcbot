# Telegram API surface

This page records the Telegram stack this checkout actually runs and the
authorization boundaries that follow from it. It is engineering reference
material, not a claim that MTProto grants privileges.

## Installed distribution

- Declared dependency: `kurigram[fast]>=2.2.27,<3` in `pyproject.toml`.
- Locked and installed version: Kurigram **2.2.27** (wheel
  `kurigram-2.2.27-py3-none-any.whl` in `uv.lock`).
- Runtime import: `pyrogram`, resolved from the project's UV-managed
  `.venv/lib/python3.14/site-packages/pyrogram/`. There is no importable
  `kurigram` module and no separate `pyrogram` distribution.
- Generated TL layer: **233**. Requests are wrapped in
  `InvokeWithLayer(layer=233)` by the session.
- The only client is built in `tcbot/database/mtproto.py` with `bot_token`,
  `api_id`, `api_hash` and a PostgreSQL-backed storage engine. There is no
  user-account login and no HTTP Bot API client in the application.

## Layers that stay separate

1. **Transport.** MTProto is Telegram's protocol. Speaking it does not grant
   rights that Telegram withholds from the authenticated identity.
2. **API surface.** Kurigram exposes generated raw TL functions beyond the
   documented HTTP Bot API subset. The bot uses one raw call directly:
   `contacts.ResolveUsername` through `Client.invoke`.
3. **Identity.** A bot-token session remains a bot. `auth.importBotAuthorization`
   does not turn it into a user account.
4. **Chat authorization.** Telegram still checks membership, the exact
   administrator right, target state, and account-level flood or privacy rules.
   A raw call cannot supply a missing `ban_users`, `delete_messages`, or
   `invite_users` right.

## Method capability matrix

| Operation | Wrapper used here | Raw TL method | Identity | Telegram-side checks |
|---|---|---|---|---|
| Ban in supergroup/channel | `Client.ban_chat_member` | `channels.editBanned` | users and bots | `CHAT_ADMIN_REQUIRED`, `RIGHT_FORBIDDEN`, `USER_NOT_PARTICIPANT`, `USER_ADMIN_INVALID`, `FLOOD_WAIT` |
| Ban in basic group | `Client.ban_chat_member` | `messages.deleteChatUser` | users and bots | `CHAT_ADMIN_REQUIRED`, `CHAT_ID_INVALID` |
| Unban / kick rejoin | `Client.unban_chat_member` | `channels.editBanned` with empty banned rights | users and bots | same `editBanned` family; no `only_if_banned` option in this version |
| Mute / unmute | `Client.restrict_chat_member` | `channels.editBanned` with `ChatBannedRights` | users and bots | same `editBanned` family; finite durations must be at least 30 seconds |
| Promote Telegram admin | `Client.promote_chat_member` exists but is **not called** | `channels.editAdmin` | users and bots | `BOT_CHANNELS_NA`, `BOT_GROUPS_BLOCKED`, `ADMIN_RANK_INVALID`, rights errors |
| Read one member | `Client.get_chat_member` | `channels.getParticipant` / `messages.getFullChat` | users and bots | `USER_NOT_PARTICIPANT`, `CHAT_ADMIN_REQUIRED` |
| Resolve username | `Client.invoke` | `contacts.ResolveUsername` | users and bots | read-only lookup; no chat admin right involved |
| Rich send / edit | `Client.send_rich_message`, `edit_message_text` | rich-message TL types | users and bots | chat write rights and rich-markup validity |
| Callback toast | `CallbackQuery.answer` | Bot API callback answer | bots | no rich payload exists for toasts |
| Keyboard clear | `edit_message_reply_markup` with empty markup | `ReplyInlineMarkup(rows=[])` | bots | the only native primitive used; carries no message content |

Federation roles in `users_roles` are database roles. Demotion before
enforcement removes a federation role; it does not call `channels.editAdmin` and
does not change Telegram administrator rights.

## Documentation record

Retrieved on 2026-11-28 for the installed version:

- Official Telegram Bot API and rich-message pages on `core.telegram.org`,
  including `channels.editBanned`, `channels.editAdmin`,
  `messages.deleteChatUser`, `editMessageReplyMarkup`, rights, and rich HTML.
- Official Kurigram repository and README, version-matched to 2.2.27.
- Context7 library `/kurigram-org/kurigram`, version 2.2.27. Version-pinned
  queries about rich-button constraints and keyboard clearing returned no
  method-level documentation; unpinned queries returned generic signature
  snippets. Those gaps were filled from the installed source and official
  Telegram documentation instead of inferred from Context7.
- The generated source tree under `.venv/lib/python3.14/site-packages/pyrogram/`
  was read for `send_rich_message`, `InputRichMessage`,
  `InputRichBlockButtons`, `RichMessageButton`, session error conversion, and
  `edit_message_reply_markup`.

No live Telegram RPC was sent while producing this record. Capability claims
come from installed source and official documentation, not from an observed
server response.
