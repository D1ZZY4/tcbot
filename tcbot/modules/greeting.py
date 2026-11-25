# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""New and left member event handlers, plus chat migration tracking."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Chat, ChatPermissions, Message, User

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import buttons, decorators
from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.context import Ctx, bot_identity, chat_id_of, display_name
from tcbot.modules.helper.handlers import (
    CHAT_MEMBER,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    MessageHandler,
)
from tcbot.modules.helper.locale import (
    locale_for_chat,
    locale_for_update,
    locale_for_user,
)
from tcbot.modules.helper.messages import (
    appeal_deep_link,
    message_link,
    reply_rich,
    reply_rich_result,
    send_text,
)
from tcbot.modules.helper.pipelines.demote_actions import demote_before_enforcement
from tcbot.utils.dispatch import is_benign_telegram_error, throw_if_cancelled
from tcbot.utils.i18n import Safe, code, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from tcbot.database.documents import BanDoc

log = get_logger(__name__)

# * Upper bound for concurrent per-member join handling (batch invite-link
# * joins). Each member costs one harvest write plus ban/mute reads and a
# * Telegram enforcement call; unbounded gather() on a large batch would
# * spike database pool pressure (default pool max 10) and Telegram burst traffic.
# * Matches the fan_out Telegram cap; members beyond the bound wait.
_MAX_CONCURRENT_JOINS: int = 10

# * One global bound for ALL concurrent join updates (not per-ctx): the
# * ctx processor runs different conversations in parallel, so each
# * new-member callback would otherwise get its own Semaphore(10), making
# * the effective Telegram+database concurrency N*10 with no ceiling.
_join_sem = asyncio.Semaphore(_MAX_CONCURRENT_JOINS)


async def _in_federation(chat_id: int, *, action: str) -> bool | None:
    """Return True when join events in ``chat_id`` must be enforced.

    Primary groups always qualify; other chats qualify only while their
    connected row is active, read directly so a disconnect in another
    process stops join enforcement at once instead of lingering for the
    connection cache TTL.

    ``None`` on a lookup outage means "unknown": callers still run the
    ban/mute reads, which fail closed. Skipping enforcement on an outage
    would let a federation-banned user join unchecked.
    """
    if cfg.is_primary_group(chat_id):
        return True
    try:
        return await db.groups_db.is_connected(chat_id, fresh=True)
    except Exception as exc:
        log.warning(
            "is_connected check failed for chat=%d on %s: %s", chat_id, action, exc
        )
        return None


async def _send_join_ban_notices(
    bot: Client,
    chat: Chat,
    member: User,
    ban: BanDoc,
    locale: str,
    *,
    reply_to: Message | None,
) -> None:
    """Send the group notice and the target DM for a ban enforced on join.

    The group notice names the identity and carries the log, proof, and
    appeal links. The DM carries the community, the group, the reason, and
    the same links, but it never repeats the group wording. A missing log or
    proof reference drops only its own button.
    """
    proof_id = int(ban.get("proof_message_id") or 0)
    log_id = int(ban.get("log_message_id") or 0)
    proof_chat, proof_thread = cfg.proofs
    logs_chat, logs_thread = cfg.logs
    log_url = message_link(logs_chat, log_id, logs_thread) if log_id else None
    proof_url = message_link(proof_chat, proof_id, proof_thread) if proof_id else None
    ban_id = str(ban.get("ban_id") or "")
    bot_username = (await bot_identity(bot)).username or ""
    appeal_url = (
        appeal_deep_link(bot_username, ban_id) if bot_username and ban_id else None
    )
    keyboard = buttons.join_ban_btn(log_url, proof_url, appeal_url, locale)
    group_text = t(
        "greeting.notice.banned_group",
        locale,
        user=Safe(user_ref(member.id, display_name(member), member.username)),
        uid=Safe(code(str(member.id))),
        first=display_name(member),
        last=member.last_name or "-",
        username=f"@{member.username}" if member.username else "-",
        ban=Safe(code(ban_id)) if ban_id else "-",
    )
    group_send = (
        reply_rich_result(reply_to, group_text, reply_markup=keyboard)
        if reply_to is not None
        else send_text(bot, chat_id_of(chat), group_text, reply_markup=keyboard)
    )
    # * The DM goes to the banned member, so it follows their locale, not
    # * the group's. Every other ban DM resolves the recipient this way.
    dm_locale = await locale_for_user(member.id)
    dm_text = t(
        "greeting.notice.banned_dm",
        dm_locale,
        community=cfg.community_name,
        group=chat.title or str(chat_id_of(chat)),
        reason=ban.get("reason") or "-",
        ban=Safe(code(ban_id)) if ban_id else "-",
    )
    dm_send = send_text(
        bot,
        member.id,
        dm_text,
        reply_markup=buttons.join_ban_btn(log_url, proof_url, appeal_url, dm_locale),
    )
    group_result, dm_result = await asyncio.gather(
        group_send,
        dm_send,
        return_exceptions=True,
    )
    throw_if_cancelled((group_result, dm_result))
    if isinstance(group_result, BaseException):
        log.warning(
            "Join ban group notice failed for uid=%d in chat=%d: %s",
            member.id,
            chat_id_of(chat),
            group_result,
        )
    if isinstance(dm_result, BaseException):
        log.debug(
            "Join ban DM failed for uid=%d in chat=%d: %s",
            member.id,
            chat_id_of(chat),
            dm_result,
        )


async def _ack_markup(member_id: int, locale: str) -> object | None:
    """Build the greeting's I agree button when the current version needs it.

    A failure to read the rules never blocks a welcome: the greeting is sent
    without a button, and the member can still join. Acknowledgement stays a
    greeting-only surface, so no button appears on channel posts or /rules.
    """
    try:
        requirement = await db.rules_db.acknowledgement_requirement()
        if requirement is None:
            return None
        version_id = requirement[0]
        if await db.rules_db.has_acknowledged(version_id, member_id):
            return None
        return rules_btn.ack_btn(version_id, member_id, locale)
    except Exception as exc:
        log.debug("Greeting acknowledgement lookup failed for %d: %s", member_id, exc)
        return None


async def _ban_state_with_retry(user_id: int) -> BanDoc | None:
    """Read the active ban once, then retry once after a brief pause.

    A single transient pool or circuit failure must not decide moderation.
    The retry is bounded so a join handler never blocks on a dead database.
    """
    try:
        return await db.bans_db.get_active_ban(user_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        await asyncio.sleep(0.1)
        return await db.bans_db.get_active_ban(user_id)


_REPAIR_REASON: str = "Fail-closed removal: rejoin could not be delivered"


async def _repair_failed_removal(chat_id: int, user_id: int, source: str) -> None:
    """Record and queue the rejoin that a fail-closed removal could not finish.

    Both writes are best effort: they run while the ban store may still be
    down, and an outage here must not hide the original removal failure. Once
    the database is reachable, the queued reconcile run finishes the unban and
    the failed kick stays visible in the moderation history.
    """
    try:
        action_id = await db.kicks_db.log_repair_kick(
            user_id, chat_id, cfg.initial_owner_id, _REPAIR_REASON
        )
        await db.enforcement_ledger.queue_kick_unban_repair(
            action_id, chat_id, cfg.initial_owner_id
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "Fail-closed repair queue failed on %s for uid=%d in chat=%d",
            source,
            user_id,
            chat_id,
        )


async def _fail_closed_join(
    bot: Client, chat_id: int, user_id: int, source: str
) -> None:
    """Remove a joiner whose ban state could not be proven clean.

    A join request is declined on the same outage in ``on_join_request``. A
    member who already joined cannot be declined, so a bounded ban followed by
    an immediate unban is the equivalent: they must join again once the
    database is reachable and enforcement can be decided. No "you are banned"
    notice is sent, but a failed unban leaves the member removed, so the rejoin
    is retried once and then recorded for durable repair.
    """
    try:
        await asyncio.wait_for(
            bot.ban_chat_member(chat_id, user_id), timeout=TELEGRAM_LOOKUP_TIMEOUT
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        # * The ban never landed, so there is nothing to undo or repair.
        log.exception(
            "Fail-closed removal failed on %s for uid=%d in chat=%d",
            source,
            user_id,
            chat_id,
        )
        return

    try:
        await asyncio.wait_for(
            bot.unban_chat_member(chat_id, user_id),
            timeout=TELEGRAM_LOOKUP_TIMEOUT,
        )
    except asyncio.CancelledError:
        await _repair_failed_removal(chat_id, user_id, source)
        raise
    except Exception as first_exc:
        # * A transient refusal or deadline must not strand the member. One
        # * bounded retry covers the common case; a benign refusal means they
        # * are already absent and needs no repair.
        try:
            await asyncio.wait_for(
                bot.unban_chat_member(chat_id, user_id),
                timeout=TELEGRAM_LOOKUP_TIMEOUT,
            )
        except asyncio.CancelledError:
            await _repair_failed_removal(chat_id, user_id, source)
            raise
        except Exception as second_exc:
            if is_benign_telegram_error(first_exc) and is_benign_telegram_error(
                second_exc
            ):
                log.debug(
                    "Fail-closed unban on %s for uid=%d in chat=%d was benign: %s",
                    source,
                    user_id,
                    chat_id,
                    second_exc,
                )
            else:
                log.exception(
                    "Fail-closed unban failed twice on %s for uid=%d in chat=%d",
                    source,
                    user_id,
                    chat_id,
                )
                await _repair_failed_removal(chat_id, user_id, source)
            return
    log.error(
        "Fail-closed removal on %s for uid=%d in chat=%d: ban state unverifiable",
        source,
        user_id,
        chat_id,
    )


async def _handle_member(
    member: User,
    msg: Message,
    chat: Chat,
    bot: Client,
    locale: str,
    *,
    greet: bool = True,
) -> None:
    """Process a single new member: cache, ban-check, then enforce ban or greet.

    A banned joiner is removed in every connected group, and both the group
    and the target receive the join-ban notice. ``greet`` only controls the
    welcome message for a clean joiner, so the ban notice is never suppressed
    in a secondary group.

    ``locale`` is resolved once by the caller: batch joins share one chat, so
    resolving it per member repeats the same read N times.
    """
    if member.is_bot:
        return

    harvest_r, ban, mute = await asyncio.gather(
        db.users_cache.harvest_user_identity(
            member.id,
            member.username,
            display_name(member),
            member.last_name,
        ),
        _ban_state_with_retry(member.id),
        db.mutes_db.get_active_mute(member.id),
        return_exceptions=True,
    )
    # ! CRITICAL: a cancelled read must propagate, never degrade into a
    # ! clean greet: shutdown would otherwise welcome a banned joiner.
    throw_if_cancelled((harvest_r, ban, mute))
    # * An unverifiable ban state is not a clean join: remove the member so a
    # * later join is checked against a healthy database. Staying silent while
    # * leaving them in the group would let a banned user in during an outage.
    _enforcement_blind = False
    if isinstance(ban, BaseException):
        log.error("get_active_ban failed on join for uid=%d: %s", member.id, ban)
        ban = None
        _enforcement_blind = True
        await _fail_closed_join(bot, chat_id_of(chat), member.id, "new_member")
        return
    if isinstance(mute, BaseException):
        log.error("get_active_mute failed on join for uid=%d: %s", member.id, mute)
        mute = None
        _enforcement_blind = True

    if ban:
        # * Best-effort demote keeps the role-vs-state invariant (a
        # * banned user must not hold a federation role). Enforcement runs
        # * unless the verdict names the protected Owner, which the guard
        # * below skips.
        enforced_role = await demote_before_enforcement(
            bot, member.id, display_name(member), trigger="ban"
        )
        if enforced_role == "owner":
            # * The protected Owner is never a valid enforcement target. The
            # * helper already logged the refusal; skip the Telegram ban.
            return
        try:
            await asyncio.wait_for(
                bot.ban_chat_member(chat_id_of(chat), member.id),
                timeout=TELEGRAM_LOOKUP_TIMEOUT,
            )
        except Exception:
            log.exception(
                "Ban on join failed for uid=%d in chat=%d",
                member.id,
                chat_id_of(chat),
            )
            return
        await _send_join_ban_notices(
            bot,
            chat,
            member,
            ban,
            locale,
            reply_to=msg,
        )
        return

    if mute:
        enforced_role = await demote_before_enforcement(
            bot, member.id, display_name(member), trigger="mute"
        )
        if enforced_role == "owner":
            log.warning(
                "Skipping mute re-apply against the protected Owner uid=%d in chat=%d",
                member.id,
                chat_id_of(chat),
            )
        else:
            until = mute.get("until_date")
            perms = ChatPermissions(can_send_messages=False)
            try:
                await asyncio.wait_for(
                    bot.restrict_chat_member(
                        chat_id_of(chat), member.id, permissions=perms, until_date=until
                    ),
                    timeout=TELEGRAM_LOOKUP_TIMEOUT,
                )
                log.info(
                    "Re-applied active federation mute for uid=%d in chat=%d",
                    member.id,
                    chat_id_of(chat),
                )
            except Exception:
                log.exception(
                    "Mute re-apply on join failed for uid=%d in chat=%d",
                    member.id,
                    chat_id_of(chat),
                )

    if greet and not _enforcement_blind:
        markup = await _ack_markup(member.id, locale)
        await reply_rich(
            msg,
            t(
                "greeting.welcome.body",
                locale,
                user=Safe(user_ref(member.id, display_name(member), member.username)),
                community=cfg.community_name,
            ),
            log_label=f"Welcome for uid={member.id}",
            reply_markup=markup,
        )


@decorators.log_execution
async def on_new_member(ctx: Ctx) -> None:
    """Enforce bans on new members in all connected groups; greet only in the main group.

    Previously this handler returned early for chats that were not the main
    group, meaning a federation-banned user who joined a secondary
    connected group would not be removed. This version checks ``is_connected``
    freshly for non-primary chats so a disconnect in another process stops
    enforcement at once, and runs ``_handle_member`` with ``greet=False`` for
    them so bans are enforced everywhere without producing welcome-message
    noise in secondary groups.
    """
    msg = ctx.effective_message
    chat = ctx.effective_chat
    if msg is None or chat is None:
        return

    is_primary = cfg.is_primary_group(chat_id_of(chat))

    # * Only act in connected federation groups; skip all other chats.
    if await _in_federation(chat_id_of(chat), action="new_member") is False:
        return

    # * One chat, one locale: resolve once for the whole batch below.
    locale = await locale_for_chat(chat)

    # * Process all new members concurrently but bounded; handles batch
    # * joins via invite links without exhausting the database pool or
    # * bursting Telegram traffic. Failures stay per-member via
    # * return_exceptions=True, as before.
    # * Shared global semaphore (module-level _join_sem); do not re-create a
    # * per-ctx Semaphore here.

    async def _bounded(m: User) -> None:
        async with _join_sem:
            await _handle_member(m, msg, chat, ctx.bot, locale, greet=is_primary)

    join_results = await asyncio.gather(
        *[_bounded(m) for m in (msg.new_chat_members or ())],
        return_exceptions=True,
    )
    throw_if_cancelled(join_results)
    # * One failed member must not hide the enforcement failure for the whole
    # * batch. The individual helper already logs its own Telegram refusal,
    # * but an unexpected error before that call only surfaced here.
    for failure in join_results:
        if isinstance(failure, BaseException) and not isinstance(
            failure, asyncio.CancelledError
        ):
            log.error(
                "Join enforcement failed in chat=%d: %s",
                chat_id_of(chat),
                failure,
                exc_info=failure,
            )


@decorators.log_execution
async def on_join_request_approved(ctx: Ctx) -> None:
    """Re-apply an active federation mute or ban when a join request is approved.

    ``on_join_request`` declines banned users at request time, but an active
    *mute* is not grounds for declining (the user is allowed in, just
    restricted), so it cannot be enforced there. Approving a join request
    does not produce a ``new_chat_members`` service message, so
    ``on_new_member`` never runs for this path either - without this handler
    a muted user could regain full posting rights simply by requesting to
    join and having an admin approve them.

    ``via_join_request`` distinguishes this from a regular invite-link/added
    join (already handled by ``on_new_member``), so no double-enforcement.
    """
    cmu = ctx.chat_member
    if cmu is None or not cmu.via_join_request:
        return
    new_member = cmu.new_chat_member
    if new_member is None or new_member.status != ChatMemberStatus.MEMBER:
        return

    user = new_member.user
    if user is None or user.is_bot:
        return

    chat = cmu.chat
    if await _in_federation(chat_id_of(chat), action="join_request_approved") is False:
        return

    # * Identity harvest in parallel with mute/ban lookups.
    # * harvest_user_identity skips the DB write when identity is unchanged (L1 hit).
    harvest_r, mute, ban = await asyncio.gather(
        db.users_cache.harvest_user_identity(
            user.id, user.username, display_name(user), user.last_name or None
        ),
        db.mutes_db.get_active_mute(user.id),
        _ban_state_with_retry(user.id),
        return_exceptions=True,
    )
    # ! CRITICAL: cancellation must propagate before any enforcement
    # ! decision; coercing it into ban=None skips the ban below.
    throw_if_cancelled((harvest_r, mute, ban))
    if isinstance(ban, BaseException):
        log.error(
            "get_active_ban failed for uid=%d on join_request_approved in chat=%d: %s",
            user.id,
            chat_id_of(chat),
            ban,
        )
        # * No later event re-checks an approved request, so silence would
        # * leave a possibly banned member in the group indefinitely.
        await _fail_closed_join(
            ctx.bot, chat_id_of(chat), user.id, "join_request_approved"
        )
        return
    if ban:
        # * The request-time decline in on_join_request can be beaten by a
        # * ban created after approval or a failed decline. Enforce here as
        # * well; ban_chat_member on an already-removed user is benign.
        # * Checked before the mute-failure early-return below so a mute-DB
        # * outage cannot disable ban enforcement on this path.
        enforced_role = await demote_before_enforcement(
            ctx.bot, user.id, display_name(user), trigger="ban"
        )
        if enforced_role == "owner":
            return
        try:
            await asyncio.wait_for(
                ctx.bot.ban_chat_member(chat_id_of(chat), user.id),
                timeout=TELEGRAM_LOOKUP_TIMEOUT,
            )
        except Exception:
            log.exception(
                "Ban on join_request_approved failed for uid=%d in chat=%d",
                user.id,
                chat_id_of(chat),
            )
            return
        locale = await locale_for_chat(chat)
        await _send_join_ban_notices(
            ctx.bot,
            chat,
            user,
            ban,
            locale,
            reply_to=None,
        )
        return
    if isinstance(mute, BaseException):
        log.warning(
            "get_active_mute failed for uid=%d on join_request_approved in chat=%d: %s",
            user.id,
            chat_id_of(chat),
            mute,
        )
        return
    if not mute:
        return

    enforced_role = await demote_before_enforcement(
        ctx.bot, user.id, display_name(user), trigger="mute"
    )
    if enforced_role == "owner":
        log.warning(
            "Skipping mute re-apply against the protected Owner uid=%d in chat=%d",
            user.id,
            chat_id_of(chat),
        )
        return
    until = mute.get("until_date")
    perms = ChatPermissions(can_send_messages=False)
    try:
        await asyncio.wait_for(
            ctx.bot.restrict_chat_member(
                chat_id_of(chat), user.id, permissions=perms, until_date=until
            ),
            timeout=TELEGRAM_LOOKUP_TIMEOUT,
        )
        log.info(
            "Re-applied active federation mute on approved join_request for uid=%d in chat=%d",
            user.id,
            chat_id_of(chat),
        )
    except Exception:
        log.exception(
            "Mute re-apply on join_request_approved failed for uid=%d in chat=%d",
            user.id,
            chat_id_of(chat),
        )


@decorators.log_execution
async def on_join_request(ctx: Ctx) -> None:
    """Decline join requests from federation-banned users in connected groups.

    When a group has join-request mode enabled (invite links require admin
    approval), Telegram delivers a ``ChatJoinRequest`` ctx instead of a
    ``new_chat_member`` status. Without this handler a banned user could
    bypass enforcement by requesting to join and waiting for an admin (or an
    auto-approve bot) to accept them.

    The handler declines the request silently when the user has an active
    federation ban. Non-banned users are left for the normal approval flow.
    Also opportunistically caches the requesting user's identity.
    """
    request = ctx.chat_join_request
    if request is None:
        return

    user = request.from_user
    if user is None or user.is_bot:
        return

    chat = request.chat
    if await _in_federation(chat_id_of(chat), action="join_request") is False:
        return

    # * The protected Owner is never a valid enforcement target, whichever
    # * join path they use. A lookup failure fails closed: the join is
    # * declined rather than admitted on an unverified owner.
    try:
        is_owner = (
            await db.users_roles.get_effective_role(user.id, fresh=True) == "owner"
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("Owner role check failed for uid=%d on join_request", user.id)
        return
    if is_owner:
        return

    # * Opportunistic identity harvest + ban check in parallel.
    # * harvest_user_identity skips the DB write when identity is unchanged (L1 hit).
    harvest_r, ban = await asyncio.gather(
        db.users_cache.harvest_user_identity(
            user.id, user.username, display_name(user), user.last_name or None
        ),
        _ban_state_with_retry(user.id),
        return_exceptions=True,
    )
    throw_if_cancelled((harvest_r, ban))
    if isinstance(ban, BaseException):
        log.error(
            "get_active_ban failed for uid=%d on join_request in chat=%d: %s",
            user.id,
            chat_id_of(chat),
            ban,
        )
        # * Fail closed on outage: decline rather than allow a possibly
        # * banned user to enter until state is proven clean.
        try:
            await ctx.bot.decline_chat_join_request(chat_id_of(chat), user.id)
        except Exception as exc:
            log.warning(
                "Failed to decline join request for uid=%d in chat=%d: %s",
                user.id,
                chat_id_of(chat),
                exc,
            )
        return

    if not ban:
        return  # not banned; let the normal approval flow proceed

    try:
        await ctx.bot.decline_chat_join_request(chat_id_of(chat), user.id)
        log.info(
            "Declined join request from federation-banned user uid=%d in chat=%d",
            user.id,
            chat_id_of(chat),
        )
    except Exception as exc:
        log.warning(
            "Failed to decline join request for uid=%d in chat=%d: %s",
            user.id,
            chat_id_of(chat),
            exc,
        )


@decorators.log_execution
async def on_left_member(ctx: Ctx) -> None:
    """Announce when a non-bot member leaves the main group."""
    msg = ctx.effective_message
    chat = ctx.effective_chat
    if msg is None or chat is None:
        return

    if not cfg.is_primary_group(chat_id_of(chat)):
        return

    member = msg.left_chat_member
    if member and not member.is_bot:
        await reply_rich(
            msg,
            t(
                "greeting.left.body",
                await locale_for_update(ctx),
                user=Safe(user_ref(member.id, display_name(member), member.username)),
            ),
            log_label="left-member",
        )


@decorators.log_execution
async def on_chat_migration(ctx: Ctx) -> None:
    """Update group records when a basic group migrates to a supergroup.

    Telegram delivers two status updates on migration:
    - ``migrate_to_chat_id`` in the old basic group (bot may no longer have
      write access at that point, so we only log it).
    - ``migrate_from_chat_id`` in the new supergroup, which carries both IDs;
      this is where we perform the DB ctx.
    """
    msg = ctx.effective_message
    if not msg:
        return

    if msg.migrate_from_chat_id:
        old_id = msg.migrate_from_chat_id
        new_id = chat_id_of(ctx.effective_chat) if ctx.effective_chat else None
        if old_id and new_id and old_id != new_id:
            # * The repoint moves the whole group in one transaction: the
            # * registry, the configuration, the membership, the open
            # * request, and the decisions of the group. The decisions
            # * carry their origin chat with them, so no second write is
            # * needed for the community-scoped ones.
            migrated = await db.groups_db.migrate_group(old_id, new_id)
            if migrated:
                log.info(
                    "Federation group migrated: old_chat_id=%d new_chat_id=%d",
                    old_id,
                    new_id,
                )
            else:
                log.debug(
                    "Chat migration received but group was not in federation: "
                    "old_chat_id=%d new_chat_id=%d",
                    old_id,
                    new_id,
                )
        return

    if msg.migrate_to_chat_id:
        log.info(
            "Chat migrate_to received: chat_id=%d -> %d "
            "(will be recorded via migrate_from in the supergroup)",
            chat_id_of(ctx.effective_chat) if ctx.effective_chat else 0,
            msg.migrate_to_chat_id,
        )


# ──────────────────────────── Handlers ──────────────────────────── #

# NOTE: The bot's own chat-member updates (MY_CHAT_MEMBER) are handled
# exclusively by connect_added.connection.on_bot_added, registered in
# connect.py. That single handler covers bot-added/promoted (join prompt,
# pending completion), bot-demoted (admin-rights-lost warning to mod channel),
# and bot-removed/kicked (federation group auto-deactivation). No second
# ChatMemberHandler is registered here to avoid Kurigram group-0 shadowing.

_MIGRATE_FILTER = filters.create(
    lambda _, __, ctx: bool(
        getattr(ctx, "migrate_to_chat_id", None)
        or getattr(ctx, "migrate_from_chat_id", None)
    ),
    name="Migrate",
)

__handlers__ = [
    ChatJoinRequestHandler(on_join_request),
    ChatMemberHandler(on_join_request_approved, CHAT_MEMBER),
    MessageHandler(filters.new_chat_members, on_new_member),
    MessageHandler(filters.left_chat_member, on_left_member),
    MessageHandler(_MIGRATE_FILTER, on_chat_migration),
]
