# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement pair probes and outcome folding for sync runs."""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest

from tcbot.utils.dispatch import is_benign_telegram_error
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from telegram import Bot

log = get_logger(__name__)

# * Bounds for one sync run. Each (user x group) pair costs at least one
# * get_chat_member read plus, on a miss, one enforcement write; an
# * unbounded cross product (bans x groups) would burn the 30 req/s global
# * Telegram budget for tens of minutes on large federations and starve
# * real commands. The cap keeps one run to roughly a minute worst case.
_SYNC_MAX_CHECKS: int = 200

# * Per-call budget for membership probes, mirroring the cleanup membership
# * check: a stalled probe must not hold its fan_out slot. Single owner in
# * tcbot.utils.time_and_date.
_MEMBER_CHECK_TIMEOUT_S: float = TELEGRAM_LOOKUP_TIMEOUT

# * Sample cap for failed-group titles in operator replies: enough to act
# * on, small enough to stay far under Telegram message limits.
_FAILED_SAMPLE_N: int = 5


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
    # * Lazy islice, never a full materialization: a 10k-ban by 100-group
    # * sweep builds two pairs, not a million-row list, before truncating.
    limit = max(0, max_checks)
    pairs = list(
        itertools.islice(((uid, cid) for uid in user_ids for cid in chat_ids), limit)
    )
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
