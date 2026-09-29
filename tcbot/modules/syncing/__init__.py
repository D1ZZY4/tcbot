# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement reconciliation across groups (/tcsync)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import MessageHandler

from tcbot import database as db
from tcbot.modules.helper import replies
from tcbot.modules.syncing.command import (
    _RL_PERIOD_BULK_S,
    _RL_SYNC_LIMIT,
    cmd_sync,
)
from tcbot.modules.syncing.core import (
    _FAILED_SAMPLE_N,
    _MEMBER_CHECK_TIMEOUT_S,
    _SYNC_MAX_CHECKS,
    SyncCounts,
    _member_status,
    _summarize,
    _sync_ban_pair,
    _sync_unban_pair,
    take_pairs,
)
from tcbot.utils.dispatch import fan_out
from tcbot.utils.formatter import bold, code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters

if TYPE_CHECKING:
    from telegram import Bot

log = get_logger(__name__)

__all__ = [
    "_FAILED_SAMPLE_N",
    "_MEMBER_CHECK_TIMEOUT_S",
    "_RL_PERIOD_BULK_S",
    "_RL_SYNC_LIMIT",
    "_SYNC_CMDS",
    "_SYNC_MAX_CHECKS",
    "SyncCounts",
    "__handlers__",
    "__help__",
    "__help_sections__",
    "__help_text__",
    "__module_name__",
    "_member_status",
    "_render_summary",
    "_summarize",
    "_sync_ban_pair",
    "_sync_unban_pair",
    "cmd_sync",
    "db",
    "get_help",
    "run_ban_sync",
    "take_pairs",
    "verify_user",
]

# ────────────────────── Module & Help Message ───────────────────── #

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
        replies.where_section(replies.context_exec_or_group(locale), locale),
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
    # * Deterministic sweep order: Mongo returns insertion order, so without a
    # * sort the truncation victims (and the audit log) would differ run to run.
    chat_ids = sorted({g.get("chat_id", 0) for g in groups if g.get("chat_id", 0)})
    titles = {
        c: (g.get("title") or str(c))
        for g in groups
        for c in [g.get("chat_id", 0)]
        if c
    }
    pairs, truncated = take_pairs(sorted(ban_uids), chat_ids, max_checks)
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
    # * Same deterministic order as the sweep above (see run_ban_sync).
    chat_ids = sorted({g.get("chat_id", 0) for g in groups if g.get("chat_id", 0)})
    titles = {
        c: (g.get("title") or str(c))
        for g in groups
        for c in [g.get("chat_id", 0)]
        if c
    }
    # * Bound like the sweep: one targeted verify must not probe hundreds
    # * of groups in a single command on a huge federation.
    pairs, truncated = take_pairs([user_id], chat_ids, _SYNC_MAX_CHECKS)
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
        t("syncing.summary.skipped", locale, n=Safe(code(str(counts.skipped)))),
        t("syncing.summary.failed", locale, n=Safe(code(str(counts.failed)))),
    ]
    if counts.failed and counts.failed_titles:
        sample = ", ".join(counts.failed_titles)
        lines.append(t("syncing.summary.failing", locale, sample=sample))
    if counts.truncated:
        lines.append(t("syncing.summary.truncated", locale))
    return "\n".join(lines)


# ──────────────────────────── Handlers ──────────────────────────── #

_SYNC_CMDS = build_prefixed_filters("tcsync") | build_prefixed_filters("tcsynchronize")

__handlers__ = [
    MessageHandler(_SYNC_CMDS, cmd_sync),
]
