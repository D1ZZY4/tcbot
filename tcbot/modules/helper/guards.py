# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Authorization gates: may the executor act, and on whom."""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import identity
from tcbot.modules.helper.locale import effective_locale, locale_for_update
from tcbot.modules.helper.messages import cb_error_edit, replies, safe_reply
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from typing import Any

    from telegram import Bot, CallbackQuery, Message, Update, User

    from tcbot.database.users_roles import RoleName

log = get_logger(__name__)

# * Rank of an unknown tier name. The tier argument is a Literal, so a typo
# * is a type error the checker reports; at runtime an unknown name must
# * still fail closed, and the highest rank only ever refuses an action.
_UNKNOWN_TIER_RANK: int = 99


def required_rank(min_role: RoleName) -> int:
    """Return the rank of the tier an executor must hold.

    An unknown tier name resolves to the highest rank, so a mistake can
    only refuse an action, never grant one.
    """
    return db.users_roles.ROLE_RANK.get(min_role, _UNKNOWN_TIER_RANK)


def outranks(executor_role: str | None, target_role: str | None) -> bool:
    """Return True when the executor outranks the target.

    Single owner of the outrank comparison. Equal rank is refused, so a
    peer can never act on a peer. A target without a federation role
    passes: there is no rank to outrank.
    """
    if not target_role:
        return True
    return db.users_roles.role_rank(executor_role) > db.users_roles.role_rank(
        target_role
    )


class EnforcementVerdict(Enum):
    """Outcome of the enforcement-time executor-versus-target check."""

    ALLOWED = "allowed"
    OUTRANKED = "outranked"
    RANK_INSUFFICIENT = "rank_insufficient"
    LOOKUP_FAILED = "lookup_failed"


class StaffAccess(Enum):
    """Outcome of a staff-tier access check."""

    ALLOWED = "allowed"
    DENIED = "denied"
    LOOKUP_FAILED = "lookup_failed"


async def staff_access(user_id: int | None, *, min_role: RoleName) -> StaffAccess:
    """Check whether *user_id* may act at the *min_role* tier.

    The owner id always passes: the owner row and the founder role can
    diverge briefly around a transfer, and the operator must keep
    access. A lookup failure fails closed and is reported apart from a
    refusal, so the caller can ask for a retry instead of denying the
    action. Cancellation always propagates.
    """
    if user_id is None:
        return StaffAccess.DENIED
    try:
        owner_r, role_r = await asyncio.gather(
            db.users_roles.is_owner(user_id, fresh=True),
            db.users_roles.get_effective_role(user_id, fresh=True),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("staff access check failed for %d: %s", user_id, exc)
        return StaffAccess.LOOKUP_FAILED
    if owner_r is True:
        return StaffAccess.ALLOWED
    if required_rank(min_role) > db.users_roles.role_rank(role_r):
        return StaffAccess.DENIED
    return StaffAccess.ALLOWED


async def enforcement_verdict(
    executor_id: int, target_id: int, *, min_role: RoleName = "tester"
) -> tuple[EnforcementVerdict, str | None]:
    """Re-check the executor against the target at enforcement time.

    The entry command compares the two roles, but an enforcement can land
    a minute later, after the proof window. A target promoted in that
    window would otherwise be actioned by a moderator who no longer
    outranks them, and the rule that refused the action at entry would be
    silently bypassed. The enforcement path therefore re-reads both roles
    fresh and applies the same rule as :func:`resolve_and_check`.

    The check fails closed: a role lookup that fails refuses the
    enforcement, exactly like the entry check does. Cancellation is not a
    lookup failure and propagates, so a shutdown never reads as a refusal.

    ``min_role`` is the lowest rank the executor must still hold. The
    tier and the outrank rule are checked here rather than in the caller,
    so a flow that forgets its own tier check cannot enforce with a
    demoted moderator.

    Returns the verdict and, when the target outranks the executor, the
    target's role label for the refusal message.
    """
    try:
        executor_role, target_role = await asyncio.gather(
            db.users_roles.get_effective_role(executor_id, fresh=True),
            db.users_roles.get_effective_role(target_id, fresh=True),
            return_exceptions=True,
        )
    except asyncio.CancelledError:
        raise
    # * A cancelled read is a shutdown, not a verdict: the cancellation is
    # * re-raised so the executor stops instead of reporting a refusal.
    throw_if_cancelled((executor_role, target_role))
    if isinstance(executor_role, BaseException) or isinstance(
        target_role, BaseException
    ):
        log.warning(
            "enforcement verdict: role lookup failed (executor=%d target=%d)",
            executor_id,
            target_id,
        )
        return EnforcementVerdict.LOOKUP_FAILED, None
    if required_rank(min_role) > db.users_roles.role_rank(executor_role):
        return EnforcementVerdict.RANK_INSUFFICIENT, None
    if not outranks(executor_role, target_role):
        return EnforcementVerdict.OUTRANKED, db.users_roles.role_label(target_role)
    return EnforcementVerdict.ALLOWED, None


def enforcement_refusal_text(
    verdict: EnforcementVerdict, target_label: str | None, locale: str | None
) -> str:
    """Render the refusal line for a refused enforcement verdict.

    Single owner for the verdict-to-prose mapping so the ban, kick, mute,
    and warn executors cannot drift apart on which verdict produces which
    notice.
    """
    if verdict is EnforcementVerdict.OUTRANKED:
        return replies.refuse_outranked(target_label or "", locale, plain=True)
    if verdict is EnforcementVerdict.RANK_INSUFFICIENT:
        return replies.refuse_rank_insufficient(locale, plain=True)
    return replies.refuse_role_lookup(locale, plain=True)


async def enforcement_refusal(
    executor_id: int,
    target_id: int,
    *,
    min_role: RoleName,
    action: str,
    locale: str | None,
) -> str | None:
    """Return the refusal notice when the executor may not act, else None.

    Single owner for the enforcement-time gate: the verdict, the refusal
    log line, and the notice text. Every executor calls this instead of
    re-implementing the check, so the four moderation paths cannot drift
    apart on the rule or on the wording. The caller owns only the
    transport that delivers the notice.
    """
    verdict, target_label = await enforcement_verdict(
        executor_id, target_id, min_role=min_role
    )
    if verdict is EnforcementVerdict.ALLOWED:
        return None
    log.warning(
        "%s refused for target=%d: executor=%d (%s)",
        action,
        target_id,
        executor_id,
        verdict.value,
    )
    return enforcement_refusal_text(verdict, target_label, locale)


async def resolve_and_check(
    msg: Message,
    executor_id: int,
    target_id: int,
    *,
    min_role: RoleName,
) -> tuple[str | None, str | None]:
    """Validate executor permission and target eligibility for moderation actions.

    Replies on the message itself when the executor lacks rank or the target
    outranks the executor, then returns ``(None, None)``.

    Both roles are read fresh. A demotion or a transfer in another process
    must never be hidden behind the cache TTL, and the check must not
    depend on a decorator having run first.

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
    if executor_lookup_failed:
        log.warning(
            "resolve_and_check executor role lookup failed for %d: %s",
            executor_id,
            executor_role,
        )
        executor_role = None
    if target_lookup_failed:
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
    if required_rank(min_role) > db.users_roles.role_rank(executor_role):
        await safe_reply(
            msg,
            replies.refuse_rank_insufficient(locale, plain=True),
            log_label="resolve_and_check rank-insufficient",
            parse_mode=None,
        )
        return None, None

    if not outranks(executor_role, target_role):
        label = db.users_roles.role_label(target_role)
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
    min_role: RoleName,
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
    min_role: RoleName,
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
    if required_rank(min_role) > db.users_roles.role_rank(role):
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


async def check_callback_staff(
    admin_id: int, q: CallbackQuery, update: Update, *, min_role: RoleName = "admin"
) -> str | None:
    """Re-check the staff rank alongside ``q.answer()`` in parallel.

    Answers the spinner immediately regardless of DB latency. Returns the
    staff role, or ``None`` after editing the perm-expired notice.
    Cancellation from either branch propagates instead of rendering.

    ``min_role`` names the lowest rank that passes. The rank table is the
    single source of truth for the comparison, so a tier that joins it
    takes part in the gate instead of slipping past a hardcoded name.
    """
    role_r, answer_r = await asyncio.gather(
        db.users_roles.get_effective_role(admin_id, fresh=True),
        q.answer(),
        return_exceptions=True,
    )
    throw_if_cancelled((role_r, answer_r))
    if isinstance(answer_r, BaseException):
        log.debug("callback answer failed: %s", answer_r)
    if isinstance(role_r, BaseException) or required_rank(
        min_role
    ) > db.users_roles.role_rank(role_r):
        await cb_error_edit(
            q,
            replies.err_perm_expired(await locale_for_update(update), plain=True),
            log_label="callback perm-expired",
            parse_mode=None,
        )
        return None
    return role_r


async def check_callback_executor(
    update: Update,
    q: CallbackQuery,
    admin: User | None,
    *,
    min_role: RoleName = "admin",
) -> str | None:
    """Refuse the anonymous-admin placeholder, then re-check the staff rank.

    The placeholder appears as the sender when a real admin posts through
    "send message as group", so the true identity is unknown. Every
    federation command refuses it, and the callback paths refuse it here
    too instead of relying on the placeholder holding no role.
    """
    if identity.is_anon_admin(admin):
        await cb_error_edit(
            q,
            replies.refuse_anon_admin(await locale_for_update(update), plain=True),
            log_label="callback anon-admin",
            parse_mode=None,
        )
        return None
    if admin is None:
        await cb_error_edit(
            q,
            replies.err_perm_expired(await locale_for_update(update), plain=True),
            log_label="callback perm-expired",
            parse_mode=None,
        )
        return None
    return await check_callback_staff(admin.id, q, update, min_role=min_role)


async def prompt_owner_mismatch(
    q: Any, update: Update, *, min_parts: int, key: str
) -> bool:
    """Answer an alert and return True when the tapper is not the prompt owner.

    New callbacks carry ``{...}:{executor}`` after the legacy shape; only
    the recorded executor (or legacy taps without an executor segment) may
    act on the prompt. ``min_parts`` is the legacy segment count for the
    callback prefix and ``key`` selects the cancel or action alert copy.
    The prompt stays live on mismatch so the opener can still finish it.

    A legacy payload names no owner, so the check cannot prove who opened
    the prompt. It therefore lets the tapper through and leaves the
    authorization to the caller's own rank check, which every prompt
    handler runs. The legacy branch must never be the last gate.
    """
    data = getattr(q, "data", "") or ""
    parts = str(data).split(":")
    if len(parts) <= min_parts:
        return False
    try:
        owner_id = int(parts[-1])
    except ValueError:
        # * Fail closed: a payload whose owner segment is not a user id
        # * cannot prove who opened the prompt, so the tapper is not
        # * treated as the owner.
        return True
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
    two-part taps have no executor segment and keep the old behaviour,
    where the caller's own rank check is the only gate.
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

    The rule is the same one the outrank check applies: the executor must
    outrank the target. On top of that, demoting an Admin needs the
    Founder, because an Admin is the tier a demotion would strip.

    Both comparisons run through the shared rank table, so a tier that
    joins it takes part in the rule instead of slipping past a hardcoded
    name. The Founder stays a named tier, because the Admin rule is about
    that one role and not about a rank number.

    A target without a removable role passes: the caller decides whether
    there is anything to demote.
    """
    if target_role is None:
        return True
    if db.users_roles.role_rank(target_role) < db.users_roles.role_rank("admin"):
        # * A target below the Admin tier follows the ordinary outrank
        # * rule, which this helper owns.
        return outranks(executor_role, target_role)
    return executor_role == "founder"


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


__all__ = [
    "EnforcementVerdict",
    "StaffAccess",
    "action_owner_mismatch",
    "banned_target_refusal",
    "can_demote_admin",
    "cancel_owner_mismatch",
    "check_callback_executor",
    "check_callback_staff",
    "classify_and_check",
    "enforcement_refusal",
    "enforcement_refusal_text",
    "enforcement_verdict",
    "outranks",
    "prompt_owner_mismatch",
    "recheck_executor_rank",
    "require_federation_origin",
    "required_rank",
    "resolve_and_check",
]
