# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement reconciliation across groups (/tcsync)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from telegram import ChatPermissions
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.database.documents import GroupDoc
from tcbot.modules.helper import decorators, extraction, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import safe_reply
from tcbot.modules.helper.pipelines.demote_flow import Demote
from tcbot.utils.dispatch import fan_out, gather_bounded, is_benign_telegram_error
from tcbot.utils.formatter import bold, code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT, to_utc

if TYPE_CHECKING:
    from collections.abc import Sequence

    from telegram import Bot, Update

log = get_logger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #

_RL_PERIOD_BULK_S: int = 300
_RL_SYNC_LIMIT: int = 2

# * Bounds for one sync run. Each (user x group) pair costs at least one
# * get_chat_member read plus, on a miss, one enforcement write; an
# * unbounded cross product (bans x groups) would burn the 30 req/s global
# * Telegram budget for tens of minutes on large federations and starve
# * real commands. The cap keeps one run to roughly a minute worst case.
_SYNC_MAX_CHECKS: int = 200

# * Telegram admits 20 requests a minute per group, and one pair costs up
# * to two requests (the membership probe plus the enforcement write), so
# * a group may carry at most eight pairs per run. Without the cap a small
# * federation queued every probe behind the rate limiter and the queued
# * requests were cancelled by their own timeout, which the sweep then
# * reported as enforcement failures that never happened.
_SYNC_MAX_PAIRS_PER_CHAT: int = 8

# * Sweep cursors. The per-group pair cap means one run cannot check every
# * banned user in every group, so each run starts where the previous one
# * stopped. Without the cursor every run would start at the first user
# * again and the users past the cap would never be checked at all.
_ban_sweep_offset: int = 0
_mute_sweep_offset: int = 0

# * Per-call budget for membership probes, mirroring the cleanup membership
# * check: a stalled probe must not hold its fan_out slot. Single owner in
# * tcbot.utils.time_and_date.
_MEMBER_CHECK_TIMEOUT_S: float = TELEGRAM_LOOKUP_TIMEOUT

# * Sample cap for failed-group titles in operator replies: enough to act
# * on, small enough to stay far under Telegram message limits.
_FAILED_SAMPLE_N: int = 5


__module_name__ = "Sync"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("syncing.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("syncing.help.commands.body", locale),
        ),
        replies.who_section(
            f"{bold('/tcsync')}: {replies.perm_dev_above(locale, plain=False)}",
            locale,
        ),
        replies.where_section(replies.context_bot_or_group(locale), locale),
        (
            "/tcsync",
            t("syncing.help.sync.body", locale),
        ),
        (
            "/tcsync <target>",
            t("syncing.help.sync_target.body", locale),
        ),
        replies.target_section(locale),
        (
            replies.sec_examples(locale),
            t("syncing.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ──────────────────────── Sync outcome model ─────────────────────── #


@dataclass(frozen=True)
class SyncCounts:
    """Per-run enforcement counters; failed titles power the operator reply."""

    checked: int = 0
    enforced_bans: int = 0
    enforced_unbans: int = 0
    enforced_mutes: int = 0
    skipped: int = 0
    failed: int = 0
    truncated: bool = False
    failed_titles: tuple[str, ...] = ()


def take_pairs(
    user_ids: list[int],
    chat_ids: list[int],
    max_checks: int,
    *,
    per_chat_cap: int = _SYNC_MAX_PAIRS_PER_CHAT,
    used: dict[int, int] | None = None,
    offset: int = 0,
) -> tuple[list[tuple[int, int]], bool, int]:
    """Take up to ``max_checks`` (user, chat) pairs in stable order.

    The pairs are user-major, so every group carries the same number of
    checks. Each group stops at ``per_chat_cap`` pairs, which keeps the
    run inside the per-group Telegram rate.

    ``used`` carries the per-group pair count from an earlier pass so two
    passes over the same groups share one budget; it is updated in place.
    ``offset`` rotates the user list so consecutive runs cover different
    users instead of starving the ones past the cap.

    Returns the pairs, whether the full cross product was truncated, and
    the number of distinct users the pairs cover.
    """
    # * Lazy islice, never a full materialization: a 10k-ban by 100-group
    # * sweep builds two pairs, not a million-row list, before truncating.
    # * User-major order spreads the sweep evenly: every chat carries the
    # * same number of pairs, so no chat is loaded past the per-chat
    # * Telegram limit while others are untouched.
    limit = max(0, max_checks)
    per_chat = used if used is not None else {}
    users = list(user_ids)
    if offset and users:
        shift = offset % len(users)
        users = users[shift:] + users[:shift]
    pairs: list[tuple[int, int]] = []
    for uid in users:
        for cid in chat_ids:
            taken = per_chat.get(cid, 0)
            if taken >= per_chat_cap:
                continue
            pairs.append((uid, cid))
            per_chat[cid] = taken + 1
            if len(pairs) >= limit:
                break
        if len(pairs) >= limit:
            break
    truncated = len(user_ids) * len(chat_ids) > len(pairs)
    covered = len({uid for uid, _ in pairs})
    return pairs, truncated, covered


async def _member_status(bot: Bot, chat_id: int, user_id: int) -> Any | BaseException:
    """Bounded get_chat_member probe; exceptions return as values for classification."""
    try:
        return await asyncio.wait_for(
            bot.get_chat_member(chat_id, user_id),
            timeout=_MEMBER_CHECK_TIMEOUT_S,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return exc


async def _sync_ban_pair(bot: Bot, chat_id: int, user_id: int) -> str:
    """Enforce one active ban in one group; return a short outcome label.

    Outcomes: ``enforced`` (banned now), ``ok`` (already kicked),
    ``absent`` (not in chat), ``privileged`` (admin/owner, cannot ban),
    ``error`` (unexpected failure, retryable).
    """
    probed = await _member_status(bot, chat_id, user_id)
    if isinstance(probed, BaseException):
        # * A benign refusal (never a member) is the desired end state,
        # * not a failure; anything else is a retryable error.
        if is_benign_telegram_error(probed):
            return "absent"
        log.debug(
            "sync member check failed for uid=%d chat=%d: %s", user_id, chat_id, probed
        )
        return "error"
    status = getattr(probed, "status", None)
    if status == ChatMemberStatus.BANNED:
        return "ok"
    if status == ChatMemberStatus.LEFT:
        return "absent"
    if status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        log.debug("sync skipping privileged uid=%d in chat=%d", user_id, chat_id)
        return "privileged"
    try:
        await asyncio.wait_for(
            bot.ban_chat_member(chat_id, user_id),
            timeout=_MEMBER_CHECK_TIMEOUT_S,
        )
    except Exception as exc:
        if is_benign_telegram_error(exc):
            return "absent"
        log.warning("sync re-ban failed for uid=%d chat=%d: %s", user_id, chat_id, exc)
        return "error"
    log.info("sync re-banned uid=%d in chat=%d", user_id, chat_id)
    return "enforced"


async def _sync_unban_pair(bot: Bot, chat_id: int, user_id: int) -> str:
    """Clear one stale kick in one group; return a short outcome label.

    Outcomes mirror :func:`_sync_ban_pair` with ``unenforced`` for a
    cleared stale kick.
    """
    probed = await _member_status(bot, chat_id, user_id)
    if isinstance(probed, BaseException):
        if is_benign_telegram_error(probed):
            return "absent"
        log.debug(
            "sync member check failed for uid=%d chat=%d: %s", user_id, chat_id, probed
        )
        return "error"
    if getattr(probed, "status", None) != ChatMemberStatus.BANNED:
        return "ok"
    try:
        await asyncio.wait_for(
            bot.unban_chat_member(chat_id, user_id, only_if_banned=True),
            timeout=_MEMBER_CHECK_TIMEOUT_S,
        )
    except Exception as exc:
        if is_benign_telegram_error(exc):
            return "absent"
        log.warning(
            "sync re-unban failed for uid=%d chat=%d: %s", user_id, chat_id, exc
        )
        return "error"
    log.info("sync cleared stale kick for uid=%d in chat=%d", user_id, chat_id)
    return "unenforced"


async def _sync_mute_pair(
    bot: Bot, chat_id: int, user_id: int, until_date: Any = None
) -> str:
    """Re-apply one active mute in one group; return a short outcome label.

    Outcomes: ``remuted`` (restricted now), ``ok`` (already restricted,
    banned, or absent), ``absent`` (not in chat), ``privileged``
    (admin/owner, cannot restrict), ``error`` (unexpected failure,
    retryable). Never unrestricts: a restricted non-muted user may hold a
    manual admin restriction that sync must not lift.
    """
    probed = await _member_status(bot, chat_id, user_id)
    if isinstance(probed, BaseException):
        # * Same benign rule as the ban pair: never a member is the
        # * desired end state, not a failure; anything else is retryable.
        if is_benign_telegram_error(probed):
            return "absent"
        log.debug(
            "sync member check failed for uid=%d chat=%d: %s", user_id, chat_id, probed
        )
        return "error"
    status = getattr(probed, "status", None)
    if status == ChatMemberStatus.RESTRICTED:
        return "ok"
    if status == ChatMemberStatus.BANNED:
        return "ok"
    if status == ChatMemberStatus.LEFT:
        return "absent"
    if status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        log.debug("sync skipping privileged uid=%d in chat=%d", user_id, chat_id)
        return "privileged"
    try:
        await asyncio.wait_for(
            bot.restrict_chat_member(
                chat_id,
                user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=(
                    to_utc(until_date)
                    if isinstance(until_date, datetime)
                    else until_date
                ),
            ),
            timeout=_MEMBER_CHECK_TIMEOUT_S,
        )
    except Exception as exc:
        if is_benign_telegram_error(exc):
            return "absent"
        log.warning("sync re-mute failed for uid=%d chat=%d: %s", user_id, chat_id, exc)
        return "error"
    log.info("sync re-muted uid=%d in chat=%d", user_id, chat_id)
    return "remuted"


def _summarize(
    pairs: list[tuple[int, int]],
    outcomes: list[str | BaseException],
    titles: dict[int, str],
    *,
    truncated: bool,
) -> tuple[SyncCounts, list[str]]:
    """Fold pair outcomes into counts plus a capped failed-group title sample."""
    counts = {"enforced": 0, "unenforced": 0, "remuted": 0, "error": 0, "skip": 0}
    failed_titles: list[str] = []
    for (uid, cid), outcome in zip(pairs, outcomes, strict=False):
        if isinstance(outcome, BaseException):
            counts["error"] += 1
            if len(failed_titles) < _FAILED_SAMPLE_N:
                failed_titles.append(titles.get(cid, str(cid)))
            log.warning("sync pair failed for uid=%d chat=%d: %s", uid, cid, outcome)
        elif outcome in ("enforced", "unenforced", "remuted", "error"):
            counts[outcome] += 1
            if outcome == "error" and len(failed_titles) < _FAILED_SAMPLE_N:
                failed_titles.append(titles.get(cid, str(cid)))
        else:
            counts["skip"] += 1
    return (
        SyncCounts(
            checked=len(pairs),
            enforced_bans=counts["enforced"],
            enforced_unbans=counts["unenforced"],
            enforced_mutes=counts["remuted"],
            skipped=counts["skip"],
            failed=counts["error"],
            truncated=truncated,
            failed_titles=tuple(failed_titles),
        ),
        failed_titles,
    )


# ──────────────────────── Sync entry points ──────────────────────── #


def _enforcement_scope(groups: Sequence[GroupDoc]) -> tuple[list[int], dict[int, str]]:
    """Return the chat IDs and titles sync must reconcile against.

    The scope is the connected groups plus the federation primary group,
    which is exactly the set the ban, mute, and unban executors enforce in.
    The primary group is not part of ``federated_groups``, so it never
    appears in ``active_groups()``; without it here a drift in the main
    group could never be repaired, since sync would never look there.

    The primary group leads the order so it always fits inside the pair
    budget: the remaining groups follow in ascending ID order, so the
    sweep order (and which pairs truncate) is identical run to run.
    """
    scope = db.groups_db.with_primary_groups(groups, (cfg.main_group,))
    entries = [
        (int(g["chat_id"]), g.get("title") or str(g["chat_id"]))
        for g in scope
        if g.get("chat_id")
    ]
    titles = dict(entries)
    rest = sorted(cid for cid, _ in entries if cid != cfg.main_group)
    main = [cfg.main_group] if cfg.main_group in titles else []
    return [*main, *rest], titles


async def _demote_staff_holdings(
    user_ids: list[int], executor_role: str | None = None
) -> None:
    """Strip staff roles from banned/muted holders before enforcement.

    ``executor_role`` of None means the system sweep (scheduled job),
    which may strip any staff role as reconcile of existing records.
    A human executor who is not the Founder must not strip ``admin``
    (``can_demote_admin`` gate); otherwise any Developer could demote
    Admin holders through ``/tcsync``.
    """
    unique = sorted({uid for uid in user_ids if uid})
    if not unique:
        return
    roles = await gather_bounded(
        [db.users_roles.get_effective_role(uid, fresh=True) for uid in unique]
    )
    holders: list[tuple[int, str]] = []
    for uid, role in zip(unique, roles, strict=False):
        if isinstance(role, BaseException):
            log.warning("sync demote role lookup failed for %d: %s", uid, role)
            continue
        if role not in db.users_roles.STAFF_ROLES:
            continue
        if role == "admin" and executor_role is not None and executor_role != "founder":
            log.warning(
                "sync kept admin role for %d: executor %s may not demote admin",
                uid,
                executor_role,
            )
            continue
        holders.append((uid, role))
    if not holders:
        return
    removed = await gather_bounded(
        [Demote.remove_role(uid, role) for uid, role in holders]
    )
    for (uid, role), result in zip(holders, removed, strict=False):
        if isinstance(result, BaseException):
            log.warning("sync demote remove_role failed for %d: %s", uid, result)
            continue
        if result:
            log.warning("sync stripped role %s from banned/muted user %d", role, uid)


async def run_ban_sync(
    bot: Bot,
    *,
    max_checks: int = _SYNC_MAX_CHECKS,
    executor_role: str | None = None,
) -> SyncCounts:
    """Sweep active bans and mutes against connected groups, bounded by ``max_checks``.

    Shared by the ``/tcsync`` command and the optional scheduled job: no
    Telegram replies inside, only logs plus the returned counts. Ban pairs
    take budget first so a huge mute backlog can never starve the ban sweep;
    a mute-fetch outage skips only the mute replay with a loud log.

    ``executor_role`` names the rank allowed to strip staff roles during the
    sweep. ``None`` means the system sweep (scheduled job), which may strip
    any staff role as a reconcile of existing records; a human executor must
    pass their own rank so a Developer cannot strip an Admin.
    """
    global _ban_sweep_offset, _mute_sweep_offset
    groups, ban_uids = await asyncio.gather(
        db.groups_db.active_groups(),
        db.bans_db.active_ban_user_ids(),
    )
    try:
        mute_docs = await db.mutes_db.active_mute_docs()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("sync sweep: active_mute_docs failed; mute replay skipped")
        mute_docs = []
    chat_ids, titles = _enforcement_scope(groups)
    # * One per-group budget for the whole sweep: the ban and mute passes
    # * share it, because a group must not receive more requests than the
    # * Telegram per-group rate allows.
    per_chat: dict[int, int] = {}
    pairs, truncated, ban_covered = take_pairs(
        sorted(ban_uids),
        chat_ids,
        max_checks,
        used=per_chat,
        offset=_ban_sweep_offset,
    )
    if ban_uids:
        _ban_sweep_offset = (_ban_sweep_offset + ban_covered) % len(ban_uids)
    # * Strip stale staff rank before enforcing.
    await _demote_staff_holdings([uid for uid, _cid in pairs], executor_role)
    # * Bounded fan-out plus per-pair probe timeout.
    outcomes: list = []
    if pairs:
        outcomes = await fan_out([_sync_ban_pair(bot, cid, uid) for uid, cid in pairs])
    mute_until = {int(d.get("user_id", 0)): d.get("until_date") for d in mute_docs}
    mute_uids = sorted(uid for uid in mute_until if uid)
    mute_truncated = False
    if mute_uids:
        mute_pairs, mute_truncated, mute_covered = take_pairs(
            mute_uids,
            chat_ids,
            max(0, max_checks - len(pairs)),
            used=per_chat,
            offset=_mute_sweep_offset,
        )
        _mute_sweep_offset = (_mute_sweep_offset + mute_covered) % len(mute_uids)
        if mute_pairs:
            mute_outcomes = await fan_out(
                [
                    _sync_mute_pair(bot, cid, uid, mute_until[uid])
                    for uid, cid in mute_pairs
                ]
            )
            pairs = [*pairs, *mute_pairs]
            outcomes = [*outcomes, *mute_outcomes]
    if not pairs:
        return SyncCounts()
    counts, _ = _summarize(
        pairs, outcomes, titles, truncated=truncated or mute_truncated
    )
    log.info(
        "sync sweep: checked=%d enforced=%d remuted=%d skipped=%d failed=%d truncated=%s",
        counts.checked,
        counts.enforced_bans,
        counts.enforced_mutes,
        counts.skipped,
        counts.failed,
        counts.truncated,
    )
    return counts


async def verify_user(
    bot: Bot, user_id: int, executor_role: str | None = None
) -> SyncCounts:
    """Verify one user both directions across every connected group."""
    groups, ban = await asyncio.gather(
        db.groups_db.active_groups(),
        db.bans_db.get_active_ban(user_id),
    )
    try:
        mute = await db.mutes_db.get_active_mute(user_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("verify_user: mute read failed for user=%d", user_id)
        mute = None
    chat_ids, titles = _enforcement_scope(groups)
    # * Bound like the sweep: one targeted verify must not probe hundreds
    # * of groups in a single command on a huge federation.
    pairs, truncated, _ = take_pairs([user_id], chat_ids, _SYNC_MAX_CHECKS)
    if not pairs:
        return SyncCounts()
    if ban or mute is not None:
        await _demote_staff_holdings([user_id], executor_role)
    if ban:
        outcomes = await fan_out(
            [_sync_ban_pair(bot, cid, user_id) for _, cid in pairs]
        )
    else:
        outcomes = await fan_out(
            [_sync_unban_pair(bot, cid, user_id) for _, cid in pairs]
        )
    if mute is not None:
        # * Re-apply the live mute alongside either direction: an approved
        # * join or a demotion gap may have restored posting rights that the
        # * active record still forbids. Never unrestricts: a restricted
        # * non-muted user may hold a manual admin restriction.
        mute_pairs, mute_truncated, _ = take_pairs(
            [user_id], chat_ids, max(0, _SYNC_MAX_CHECKS - len(pairs))
        )
        if mute_pairs:
            mute_outcomes = await fan_out(
                [
                    _sync_mute_pair(bot, cid, user_id, mute.get("until_date"))
                    for _, cid in mute_pairs
                ]
            )
            pairs = [*pairs, *mute_pairs]
            outcomes = [*outcomes, *mute_outcomes]
            truncated = truncated or mute_truncated
    counts, _ = _summarize(pairs, outcomes, titles, truncated=truncated)
    return counts


def _render_summary(
    counts: SyncCounts, *, target: str, locale: str | None = None
) -> str:
    """Render the operator-facing sync summary (MarkdownV2; titles escaped)."""
    lines = [
        t("syncing.summary.title", locale, target=target),
        t("syncing.summary.checked", locale, n=Safe(code(str(counts.checked)))),
        t("syncing.summary.rebanned", locale, n=Safe(code(str(counts.enforced_bans)))),
        t(
            "syncing.summary.reunbanned",
            locale,
            n=Safe(code(str(counts.enforced_unbans))),
        ),
        t("syncing.summary.remuted", locale, n=Safe(code(str(counts.enforced_mutes)))),
        t("syncing.summary.skipped", locale, n=Safe(code(str(counts.skipped)))),
        t("syncing.summary.failed", locale, n=Safe(code(str(counts.failed)))),
    ]
    if counts.failed and counts.failed_titles:
        sample = ", ".join(counts.failed_titles)
        lines.append(t("syncing.summary.failing", locale, sample=sample))
    if counts.truncated:
        lines.append(t("syncing.summary.truncated", locale))
    return "\n".join(lines)


# ─────────────────── Command Sync </tcsync> ─────────────────── #


@decorators.ratelimiter(limit=_RL_SYNC_LIMIT, period=_RL_PERIOD_BULK_S)
@decorators.mod_only
@decorators.log_execution
async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reconcile enforcement state across connected groups, bounded per run."""
    msg = update.effective_message
    executor = update.effective_user
    if msg is None or executor is None:
        return
    locale = await locale_for_update(update)
    if not await decorators.require_federation_origin(
        msg,
        chat_id=msg.chat.id,
        chat_type=msg.chat.type,
        locale=locale,
        allow_private=True,
        log_label="cmd_sync origin",
    ):
        return
    args = parse_cmd_args(msg.text)

    # * Targeted runs enforce one user both directions, so they carry the
    # * same executor-versus-target rank gate as direct unban. The bare
    # * sweep reconciles existing records and has no single target to gate,
    # * but the executor rank still decides which staff roles the sweep may
    # * strip: a Developer must not remove an Admin's role.
    target_id: int | None = None
    executor_role: str | None = None
    if args:
        try:
            target_id, _ = await extraction.extract_target(update, args, ctx.bot)
        except Exception:
            log.exception("extract_target failed during sync")
            target_id = None
        if not target_id:
            await safe_reply(
                msg,
                replies.err_cannot_resolve(locale, plain=True),
                log_label="cmd_sync no-target",
                parse_mode=None,
            )
            return
        checked = await decorators.resolve_and_check(
            msg, executor.id, target_id, min_role="developer"
        )
        if checked == (None, None):
            return
        executor_role = checked[0]
    else:
        # * Fail closed: without the executor rank the sweep would run with
        # * system-sweep semantics and could strip an Admin's role.
        role_r = await db.users_roles.get_effective_role(executor.id, fresh=True)
        if not isinstance(role_r, str):
            log.warning("cmd_sync executor role lookup failed: %s", role_r)
            await safe_reply(
                msg,
                replies.err_db_retry(locale, plain=True),
                log_label="cmd_sync role-lookup-failed",
                parse_mode=None,
            )
            return
        executor_role = role_r

    try:
        status = await msg.reply_text(t("syncing.status.sending", locale, plain=True))
    except Exception as exc:
        log.debug("sync status reply failed: %s", exc)
        status = None

    try:
        if target_id is not None:
            counts = await verify_user(ctx.bot, target_id, executor_role)
            text = _render_summary(
                counts,
                target=t("syncing.target.user", locale, id=target_id, plain=True),
                locale=locale,
            )
        else:
            counts = await run_ban_sync(ctx.bot, executor_role=executor_role)
            text = _render_summary(
                counts,
                target=t("syncing.target.sweep", locale, plain=True),
                locale=locale,
            )
    except Exception:
        log.exception("sync run failed")
        text = replies.err_groups_load_failed(locale, plain=False)

    if status is not None:
        try:
            await status.edit_text(text, parse_mode="MarkdownV2")
            return
        except Exception as exc:
            log.debug("sync status edit failed: %s", exc)
    await safe_reply(msg, text, log_label="sync summary")


# ──────────────────────────── Handlers ──────────────────────────── #

_SYNC_CMDS = build_prefixed_filters("tcsync") | build_prefixed_filters("tcsynchronize")

__handlers__ = [
    MessageHandler(_SYNC_CMDS, cmd_sync),
]
