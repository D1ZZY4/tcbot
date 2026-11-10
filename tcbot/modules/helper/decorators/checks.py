# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Executor-vs-target permission checks shared by moderation entries."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import extraction, identity, replies
from tcbot.modules.helper.locale import effective_locale, locale_for_update
from tcbot.modules.helper.messages import safe_edit_cb, safe_reply
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

if TYPE_CHECKING:
    from typing import Any

    from telegram import Bot, CallbackQuery, Message, Update, User

    from tcbot.modules.helper.identity import Identity

log = get_logger(__name__)


async def resolve_and_check(
    msg: Message,
    executor_id: int,
    target_id: int,
    *,
    min_role: str,
) -> tuple[str | None, str | None]:
    """Validate executor permission and target eligibility for moderation actions.

    Replies on the message itself when the executor lacks rank or the target
    outranks the executor, then returns ``(None, None)``.

    On success, returns ``(executor_role, target_role)``.
    """
    executor_role, target_role = await asyncio.gather(
        db.users_roles.get_effective_role(executor_id, fresh=True),
        db.users_roles.get_effective_role(target_id, fresh=True),
        return_exceptions=True,
    )
    throw_if_cancelled((executor_role, target_role))
    # * Moderation replies render in the group locale like every other
    # * command reply; resolution never raises (falls back to default).
    chat = msg.chat
    locale = await effective_locale(
        getattr(chat, "type", None), executor_id, getattr(chat, "id", 0)
    )
    executor_lookup_failed = isinstance(executor_role, BaseException)
    target_lookup_failed = isinstance(target_role, BaseException)
    if isinstance(executor_role, BaseException):
        log.warning(
            "resolve_and_check executor role lookup failed for %d: %s",
            executor_id,
            executor_role,
        )
        executor_role = None
    if isinstance(target_role, BaseException):
        log.warning(
            "resolve_and_check target role lookup failed for %d: %s",
            target_id,
            target_role,
        )
        target_role = None
    if executor_lookup_failed or target_lookup_failed:
        await safe_reply(
            msg,
            replies.refuse_role_lookup(locale, plain=True),
            log_label="resolve_and_check role-lookup",
            parse_mode=None,
        )
        return None, None
    if db.users_roles.role_rank(executor_role) < db.users_roles.role_rank(min_role):
        await safe_reply(
            msg,
            replies.refuse_rank_insufficient(locale, plain=True),
            log_label="resolve_and_check rank-insufficient",
            parse_mode=None,
        )
        return None, None

    if target_role and db.users_roles.role_rank(
        executor_role
    ) <= db.users_roles.role_rank(target_role):
        label = db.users_roles.ROLE_LABEL.get(target_role, target_role.capitalize())
        await safe_reply(
            msg,
            replies.refuse_outranked(label, locale, plain=True),
            log_label="resolve_and_check outrank",
            parse_mode=None,
        )
        return None, None

    return executor_role, target_role


async def classify_and_check(
    bot: Bot,
    admin_id: int,
    target_id: int,
    target_name: str | None,
    msg: Message,
    *,
    action: str,
    min_role: str,
    target_is_bot: bool | None = None,
) -> tuple[identity.Identity, str | None] | None:
    """Classify the target and validate executor rank in parallel, fail closed.

    Returns ``(ident, target_role)`` on success, or ``None`` after replying on
    the message when a lookup failed or the executor is not allowed to act.
    Cancellation always propagates.
    """
    ident, role_result = await asyncio.gather(
        identity.classify(
            bot, admin_id, target_id, target_name, target_is_bot=target_is_bot
        ),
        resolve_and_check(msg, admin_id, target_id, min_role=min_role),
        return_exceptions=True,
    )
    throw_if_cancelled((ident, role_result))
    if isinstance(ident, BaseException) or isinstance(role_result, BaseException):
        # * Fail closed with a retry reply (was silent): a classify
        # * failure must not leave the moderator staring at a dead command.
        if isinstance(ident, BaseException):
            log.exception("identity.classify failed in %s: %s", action, ident)
        if isinstance(role_result, BaseException):
            log.exception("resolve_and_check failed in %s: %s", action, role_result)
        chat = msg.chat
        locale = await effective_locale(
            getattr(chat, "type", None), admin_id, getattr(chat, "id", 0)
        )
        await safe_reply(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label=f"classify_and_check {action} failed",
            parse_mode=None,
        )
        return None
    # * isinstance + early return above already narrows role_result to the
    # * success tuple (asserts vanish under python -O). Guard first: when
    # * resolve_and_check already replied and rejected (e.g. target outranks
    # * executor), return so the caller does not send a second reply.
    executor_role, target_role = role_result
    if executor_role is None:
        return None
    return ident, target_role


async def recheck_executor_rank(
    msg: Message,
    executor_id: int,
    *,
    min_role: str,
) -> bool:
    """Re-verify the executor still meets ``min_role`` at enforcement time.

    Conversation Done/Skip/Continue taps can land long after the entry
    command passed its decorator: a moderator demoted mid-window must not
    enforce. Returns True when the tap may proceed, False after replying
    on ``msg`` when the rank lapsed or the lookup failed (fail closed).
    Cancellation always propagates.
    """
    chat = msg.chat
    locale = await effective_locale(
        getattr(chat, "type", None), executor_id, getattr(chat, "id", 0)
    )
    try:
        role = await db.users_roles.get_effective_role(executor_id, fresh=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("recheck executor role lookup failed for %d: %s", executor_id, exc)
        await safe_reply(
            msg,
            replies.refuse_role_lookup(locale, plain=True),
            log_label="recheck role-lookup",
            parse_mode=None,
        )
        return False
    if db.users_roles.role_rank(role) < db.users_roles.role_rank(min_role):
        await safe_reply(
            msg,
            replies.refuse_rank_insufficient(locale, plain=True),
            log_label="recheck rank-insufficient",
            parse_mode=None,
        )
        return False
    return True


async def require_federation_origin(
    msg: Message,
    *,
    chat_id: int,
    chat_type: str,
    locale: str | None,
    allow_private: bool = True,
    log_label: str = "federation origin",
) -> bool:
    """Return True when the origin chat may host federation moderation.

    Private is allowed only when ``allow_private`` is set (federation-wide
    ban/unban/sync entries). Every group-like origin must be a connected
    group or a primary group: a disconnected group must not drive
    federation-wide enforcement or, for warns, record audit rows under a
    non-federation chat id that later aggregate into a federation threshold ban.
    Fail closed: a connection-state outage replies with the database retry
    notice and blocks the action. Cancellation always propagates.
    """
    if chat_type == "private":
        if allow_private:
            return True
        await safe_reply(
            msg,
            replies.err_group_only(locale, plain=True),
            log_label=log_label,
            parse_mode=None,
        )
        return False
    if cfg.is_primary_group(chat_id):
        return True
    try:
        connected = await db.groups_db.is_connected(chat_id, fresh=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("is_connected check failed for chat=%d: %s", chat_id, exc)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label=log_label,
            parse_mode=None,
        )
        return False
    if not connected:
        await safe_reply(
            msg,
            replies.err_group_not_found(locale, plain=True),
            log_label=log_label,
            parse_mode=None,
        )
        return False
    return True


# * One owner for the executor-plus-target fetch so a future fix cannot
# * land in one command and miss the other. Gathers stay parallel so the
# * hot path costs one cached round trip, never two serial ones.
async def resolve_executor_target(
    msg: Message,
    admin_id: int,
    update: Update,
    args: list[str],
    bot: Bot | None,
    *,
    action: str,
    locale: str | None = None,
) -> tuple[str, int, str | None] | None:
    """Fetch executor role and target in parallel, fail closed.

    Returns ``(executor_role, target_id, target_fname)`` or ``None`` when
    the caller must return (retry reply already sent, or a genuinely
    role-less executor denied silently like the decorator would).
    Callers pass their already-resolved locale so the two DB reads behind
    locale resolution do not run twice per command.
    """
    if locale is None:
        locale = await locale_for_update(update)
    _exec_r, _target_r = await asyncio.gather(
        db.users_roles.get_effective_role(admin_id, fresh=True),
        extraction.extract_target(update, args, bot),
        return_exceptions=True,
    )
    throw_if_cancelled((_exec_r, _target_r))
    if isinstance(_exec_r, BaseException):
        # * Fail closed on transient outage instead of going silently dead.
        # * A genuinely role-less caller gets None below; the decorator
        # * denies them properly on retry.
        log.warning("cmd_%s executor role lookup failed: %s", action, _exec_r)
        await safe_reply(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label=f"cmd_{action} lookup-fail",
            parse_mode=None,
        )
        return None
    executor_role = _exec_r
    if executor_role is None:
        return None
    if isinstance(_target_r, BaseException):
        log.error("extract_target failed during %s: %s", action, _target_r)
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label=f"cmd_{action} no-target",
            parse_mode=None,
        )
        return None
    target_id, target_fname = _target_r
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label=f"cmd_{action} no-target-id",
            parse_mode=None,
        )
        return None
    return executor_role, target_id, target_fname


async def classify_and_load_role(
    bot: Bot,
    admin_id: int,
    target_id: int,
    target_fname: str | None,
    msg: Message,
    *,
    action: str,
    locale: str | None = None,
) -> tuple[Identity, str | None] | None:
    """Classify the target and load its live role in parallel, fail closed.

    Returns ``(ident, current_role)`` or ``None`` when the caller must
    return (retry reply already sent). Cancellation always propagates.
    """
    ident_r, role_r = await asyncio.gather(
        identity.classify(bot, admin_id, target_id, target_fname),
        db.users_roles.get_effective_role(target_id, fresh=True),
        return_exceptions=True,
    )
    throw_if_cancelled((ident_r, role_r))
    if isinstance(ident_r, BaseException):
        log.error(
            "identity.classify failed during %s for target=%d: %s",
            action,
            target_id,
            ident_r,
        )
        await safe_reply(
            msg,
            t("admins.error.classify_failed", locale, plain=True),
            log_label=f"cmd_{action} classify-failed",
            parse_mode=None,
        )
        return None
    if isinstance(role_r, BaseException):
        log.error(
            "target role lookup failed during %s for target=%d: %s",
            action,
            target_id,
            role_r,
        )
        await safe_reply(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label=f"cmd_{action} role-lookup-failed",
            parse_mode=None,
        )
        return None
    return ident_r, role_r


async def check_callback_staff(
    admin_id: int, q: CallbackQuery, update: Update
) -> str | None:
    """Re-check Founder/Admin rank alongside ``q.answer()`` in parallel.

    Answers the spinner immediately regardless of DB latency. Returns the
    staff role, or ``None`` after editing the perm-expired notice.
    Cancellation from either branch propagates instead of rendering.
    """
    role_r, answer_r = await asyncio.gather(
        db.users_roles.get_effective_role(admin_id, fresh=True),
        q.answer(),
        return_exceptions=True,
    )
    throw_if_cancelled((role_r, answer_r))
    if isinstance(answer_r, BaseException):
        log.debug("callback answer failed: %s", answer_r)
    if isinstance(role_r, BaseException) or role_r not in ("founder", "admin"):
        await safe_edit_cb(
            q,
            replies.err_perm_expired(await locale_for_update(update), plain=True),
            parse_mode=None,
            reply_markup=None,
            log_level="debug",
            log_label="callback perm-expired",
            catch_all=True,
        )
        return None
    return role_r


async def prompt_owner_mismatch(
    q: Any, update: Update, *, min_parts: int, key: str
) -> bool:
    """Answer an alert and return True when the tapper is not the prompt owner.

    New callbacks carry ``{...}:{executor}`` after the legacy shape; only
    the recorded executor (or legacy taps without an executor segment) may
    act on the prompt. ``min_parts`` is the legacy segment count for the
    callback prefix and ``key`` selects the cancel or action alert copy.
    The prompt stays live on mismatch so the opener can still finish it.
    """
    data = getattr(q, "data", "") or ""
    parts = str(data).split(":")
    if len(parts) <= min_parts:
        return False
    try:
        owner_id = int(parts[-1])
    except ValueError:
        return False
    tapper = update.effective_user
    if tapper is None or tapper.id == owner_id:
        return False
    try:
        await q.answer(
            t(key, await locale_for_update(update), plain=True),
            show_alert=True,
        )
    except Exception as exc:
        log.debug("Prompt owner answer failed: %s", exc)
    return True


async def cancel_owner_mismatch(q: Any, update: Update) -> bool:
    """Return True when the tapper may not cancel this prompt.

    Cancel callbacks carry ``{target}:{executor}`` (3 parts); legacy
    two-part taps have no executor segment and keep the old behaviour.
    """
    return await prompt_owner_mismatch(
        q, update, min_parts=2, key="admins.error.not_prompt_owner"
    )


async def action_owner_mismatch(q: Any, update: Update, *, min_parts: int) -> bool:
    """Return True when the tapper may not act on this prompt.

    Action callbacks carry the opener as the last segment; legacy taps
    without it act as the tapper with a fresh rank re-check downstream.
    """
    return await prompt_owner_mismatch(
        q, update, min_parts=min_parts, key="admins.error.not_prompt_actor"
    )


def can_demote_admin(executor_role: str | None, target_role: str | None) -> bool:
    """Return True when the executor may demote a target holding ``target_role``.

    Only an Admin target is restricted: demoting one needs the Founder.
    Every other target follows the normal rank rule handled by the caller.
    """
    return not (target_role == "admin" and executor_role != "founder")


async def banned_target_refusal(
    target_id: int,
    locale: str | None,
    *,
    log_label: str,
) -> str | None:
    """Return a refusal line when the target holds an active ban.

    A banned user must not gain federation rank. The ban is enforced per
    group by Telegram, not by the bot's own role resolution, so a banned
    holder of a staff role keeps moderating from every chat where the ban
    did not land (including DMs). This mirrors the ownership-transfer
    guard, which already refuses a banned successor.

    Fails closed: a failed ban lookup refuses the action instead of
    granting rank on an unknown state. Cancellation always propagates.
    """
    try:
        target_ban = await db.bans_db.get_active_ban(target_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("%s ban lookup failed for %d: %s", log_label, target_id, exc)
        return replies.err_db_retry(locale, plain=True)
    if target_ban is not None:
        return t("admins.error.banned_target", locale, plain=True)
    return None


@dataclass(frozen=True)
class ModTarget:
    """Resolved moderation target shared by the ban/kick/mute/warn entries.

    ``args`` are the raw command tokens and ``has_explicit_target`` tells the
    reason parser whether the first token was consumed as the target.
    """

    msg: Message
    admin: User
    locale: str
    target_id: int
    target_name: str | None
    has_explicit_target: bool
    args: list[str]
    ident: identity.Identity
    target_role: str | None


async def resolve_mod_target(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    action: str,
    min_role: str,
    allow_private: bool,
    log_prefix: str,
    bot_check: bool = False,
) -> ModTarget | None:
    """Run the shared entry sequence for reason/proof moderation commands.

    Resolves the locale, checks the federation origin, extracts the target,
    and runs the identity plus rank checks, replying and returning ``None``
    on any failure. The caller keeps only duty-specific parsing (reason,
    duration) and conversation setup. Cancellation always propagates.
    """
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None or ctx.user_data is None:
        return None
    locale = await locale_for_update(update)
    if not await require_federation_origin(
        msg,
        chat_id=msg.chat.id,
        chat_type=msg.chat.type,
        locale=locale,
        allow_private=allow_private,
        log_label=f"{log_prefix} origin",
    ):
        return None
    args = parse_cmd_args(msg.text)
    # * Resolution plus consumption in one call: a verified explicit
    # * ID/@username overrides the reply target, and the consumed flag
    # * tells the reason parser to drop args[0] as the target token.
    (target_id, target_name), has_explicit_target = await extraction.extract_mod_target(
        update, args, ctx.bot
    )
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label=f"{log_prefix} no-target",
            parse_mode=None,
        )
        return None
    # * Warn needs a verified bot check before classifying so a proven bot
    # * target is refused instead of warned; other actions classify bots
    # * from the identity cache alone.
    target_is_bot = (
        await identity.is_proven_bot(update, target_id, ctx.bot) if bot_check else None
    )
    classified = await classify_and_check(
        ctx.bot,
        admin.id,
        target_id,
        target_name,
        msg,
        action=action,
        min_role=min_role,
        target_is_bot=target_is_bot,
    )
    if classified is None:
        return None
    ident, target_role = classified
    refusal = identity.refuse_message(action, ident, locale)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label=f"{log_prefix} refusal")
        return None
    return ModTarget(
        msg=msg,
        admin=admin,
        locale=locale,
        target_id=target_id,
        target_name=target_name,
        has_explicit_target=has_explicit_target,
        args=args,
        ident=ident,
        target_role=target_role,
    )
