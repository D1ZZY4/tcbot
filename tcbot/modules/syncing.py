# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement reconciliation: re-drive missed bans/unbans across groups (/tcsync)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest
from telegram.ext import ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.modules.helper import decorators, extraction, replies
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.dispatch import (
    fan_out,
    is_benign_telegram_error,
)
from tcbot.utils.formatter import bold, code, esc
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from telegram import Bot, Update

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #

_RL_PERIOD_BULK_S: int = 300
_RL_SYNC_LIMIT: int = 2

# * Bounds for one sync run. Each (user x group) pair costs at least one
# * get_chat_member read plus, on a miss, one enforcement write; an
# * unbounded cross product (bans x groups) would burn the 30 req/s global
# * Telegram budget for tens of minutes on large federations and starve
# * real commands. The cap keeps one run to roughly a minute worst case.
_SYNC_MAX_CHECKS: int = 200

# * Per-call budget for membership probes, mirroring the cleanup membership
# * check: a stalled probe must not hold its fan_out slot.
_MEMBER_CHECK_TIMEOUT_S: float = 3.0

# * Sample cap for failed-group titles in operator replies: enough to act
# * on, small enough to stay far under Telegram message limits.
_FAILED_SAMPLE_N: int = 5


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Sync"

__help_text__ = (
    "Reconcile enforcement state: re\\-apply bans the fan\\-out missed and "
    "verify unbans actually landed\\."
)

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        f"{code('/tcsync')} \\(alias: {code('/tcsynchronize')}\\)\n"
        f"{code('/tcsync <target>')}",
    ),
    replies.who_section(
        f"{bold('/tcsync')}: {replies.PERM_DEV_ABOVE}",
    ),
    replies.where_section(replies.CONTEXT_EXEC_OR_GROUP),
    replies.target_section(),
    (
        "/tcsync",
        "Sweeps active federation bans against connected groups \\(bounded, "
        "200 membership checks per run\\) and re\\-bans users who are present "
        "but not kicked\\. Users already kicked, absent, or privileged are "
        "skipped, never treated as failures\\.",
    ),
    (
        "/tcsync <target>",
        "Verifies one user both directions across every connected group: "
        "re\\-ban when an active ban is unenforced, unban when a stale kick "
        "survived a deactivation\\.",
    ),
    (
        replies.SEC_EXAMPLES,
        f"{code('/tcsync')}\n{code('/tcsync @username')}\n{code('/tcsync 123456789')}",
    ),
]

__help__: replies.HelpEntry = {
    "name": __module_name__,
    "overview": __help_text__,
    "sections": __help_sections__,
}


# ──────────────────────── Sync outcome model ─────────────────────── #


@dataclass(frozen=True)
class SyncCounts:
    """Per-run enforcement counters; failed titles power the operator reply."""

    checked: int = 0
    enforced_bans: int = 0
    enforced_unbans: int = 0
    skipped: int = 0
    failed: int = 0
    truncated: bool = False
    failed_titles: tuple[str, ...] = ()


def take_pairs(
    user_ids: list[int], chat_ids: list[int], max_checks: int
) -> tuple[list[tuple[int, int]], bool]:
    """Take up to ``max_checks`` (user, chat) pairs in stable order.

    Pure function (no I/O) so the bounding policy is unit-testable: callers
    never build an unbounded cross product. Returns the pairs plus whether
    the full cross product was truncated.
    """
    pairs = [(uid, cid) for uid in user_ids for cid in chat_ids][: max(0, max_checks)]
    return pairs, len(user_ids) * len(chat_ids) > len(pairs)


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
        if isinstance(probed, BadRequest) or is_benign_telegram_error(probed):
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
        await bot.ban_chat_member(chat_id, user_id)
    except Exception as exc:
        if isinstance(exc, BadRequest) or is_benign_telegram_error(exc):
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
        if isinstance(probed, BadRequest) or is_benign_telegram_error(probed):
            return "absent"
        log.debug(
            "sync member check failed for uid=%d chat=%d: %s", user_id, chat_id, probed
        )
        return "error"
    if getattr(probed, "status", None) != ChatMemberStatus.BANNED:
        return "ok"
    try:
        await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
    except Exception as exc:
        if isinstance(exc, BadRequest) or is_benign_telegram_error(exc):
            return "absent"
        log.warning(
            "sync re-unban failed for uid=%d chat=%d: %s", user_id, chat_id, exc
        )
        return "error"
    log.info("sync cleared stale kick for uid=%d in chat=%d", user_id, chat_id)
    return "unenforced"


def _summarize(
    pairs: list[tuple[int, int]],
    outcomes: list[str | BaseException],
    titles: dict[int, str],
    *,
    truncated: bool,
) -> tuple[SyncCounts, list[str]]:
    """Fold pair outcomes into counts plus a capped failed-group title sample."""
    counts = {"enforced": 0, "unenforced": 0, "error": 0, "skip": 0}
    failed_titles: list[str] = []
    for (uid, cid), outcome in zip(pairs, outcomes, strict=False):
        if isinstance(outcome, BaseException):
            counts["error"] += 1
            if len(failed_titles) < _FAILED_SAMPLE_N:
                failed_titles.append(titles.get(cid, str(cid)))
            log.warning("sync pair failed for uid=%d chat=%d: %s", uid, cid, outcome)
        elif outcome in ("enforced", "unenforced", "error"):
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
            skipped=counts["skip"],
            failed=counts["error"],
            truncated=truncated,
            failed_titles=tuple(failed_titles),
        ),
        failed_titles,
    )


# ──────────────────────── Sync entry points ──────────────────────── #


async def run_ban_sync(bot: Bot, *, max_checks: int = _SYNC_MAX_CHECKS) -> SyncCounts:
    """Sweep active bans against connected groups, bounded by ``max_checks``.

    Shared by the ``/tcsync`` command and the optional scheduled job: no
    Telegram replies inside, only logs plus the returned counts.
    """
    groups, ban_uids = await asyncio.gather(
        db.groups_db.active_groups(),
        db.bans_db.active_ban_user_ids(),
    )
    chat_ids = [g.get("chat_id", 0) for g in groups if g.get("chat_id", 0)]
    titles = {
        c: (g.get("title") or str(c))
        for g in groups
        for c in [g.get("chat_id", 0)]
        if c
    }
    pairs, truncated = take_pairs(ban_uids, chat_ids, max_checks)
    if not pairs:
        return SyncCounts()
    # * Bounded like every other federation-wide Telegram burst: the fan_out
    # * semaphore plus the per-pair probe timeout cap the blast radius.
    outcomes = await fan_out([_sync_ban_pair(bot, cid, uid) for uid, cid in pairs])
    counts, _ = _summarize(pairs, outcomes, titles, truncated=truncated)
    log.info(
        "sync sweep: checked=%d enforced=%d skipped=%d failed=%d truncated=%s",
        counts.checked,
        counts.enforced_bans,
        counts.skipped,
        counts.failed,
        counts.truncated,
    )
    return counts


async def verify_user(bot: Bot, user_id: int) -> SyncCounts:
    """Verify one user both directions across every connected group."""
    groups, ban = await asyncio.gather(
        db.groups_db.active_groups(),
        db.bans_db.get_active_ban(user_id),
    )
    chat_ids = [g.get("chat_id", 0) for g in groups if g.get("chat_id", 0)]
    titles = {
        c: (g.get("title") or str(c))
        for g in groups
        for c in [g.get("chat_id", 0)]
        if c
    }
    pairs = [(user_id, cid) for cid in chat_ids]
    if not pairs:
        return SyncCounts()
    if ban:
        outcomes = await fan_out(
            [_sync_ban_pair(bot, cid, user_id) for _, cid in pairs]
        )
    else:
        outcomes = await fan_out(
            [_sync_unban_pair(bot, cid, user_id) for _, cid in pairs]
        )
    counts, _ = _summarize(pairs, outcomes, titles, truncated=False)
    return counts


def _render_summary(counts: SyncCounts, *, target: str) -> str:
    """Render the operator-facing sync summary (MarkdownV2; titles escaped)."""
    lines = [
        f"{bold('Sync complete')} \\({esc(target)}\\)",
        f"Checked: {code(str(counts.checked))}",
        f"Re-banned: {code(str(counts.enforced_bans))}",
        f"Re-unbanned: {code(str(counts.enforced_unbans))}",
        f"Skipped: {code(str(counts.skipped))}",
        f"Failed: {code(str(counts.failed))}",
    ]
    if counts.failed and counts.failed_titles:
        sample = ", ".join(counts.failed_titles)
        lines.append(f"Still failing in: {esc(sample)}")
    if counts.truncated:
        lines.append("Note: pair cap reached; re\\-run to continue the sweep\\.")
    return "\n".join(lines)


# ─────────────────── Command Sync </tcsync> ─────────────────── #


@decorators.ratelimiter(limit=_RL_SYNC_LIMIT, period=_RL_PERIOD_BULK_S)
@decorators.mod_only
@decorators.log_execution
async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reconcile enforcement state across connected groups, bounded per run."""
    msg = update.effective_message
    if msg is None:
        return
    args = parse_cmd_args(msg.text)

    try:
        status = await msg.reply_text("Syncing enforcement state...")
    except Exception as exc:
        log.debug("sync status reply failed: %s", exc)
        status = None

    try:
        if args:
            try:
                target_id, _ = await extraction.extract_target(update, args, ctx.bot)
            except Exception:
                log.exception("extract_target failed during sync")
                target_id = None
            if not target_id:
                raise ValueError("unresolvable")
            counts = await verify_user(ctx.bot, target_id)
            text = _render_summary(counts, target=f"user {target_id}")
        else:
            counts = await run_ban_sync(ctx.bot)
            text = _render_summary(counts, target="federation sweep")
    except ValueError:
        text = esc(replies.ERR_CANNOT_RESOLVE)
    except Exception:
        log.exception("sync run failed")
        text = esc(replies.ERR_GROUPS_LOAD_FAILED)

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
