# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared reply and help-text strings used across multiple command modules."""

from __future__ import annotations

from typing import TypedDict

from tcbot.utils.i18n import t


class HelpEntry(TypedDict):
    """Typed container for a module's user-facing help content."""

    name: str
    overview: str
    sections: list[tuple[str, str]]


# ──────────────────────── Target Syntax ─────────────────────────── #


def target_syntax(locale: str | None = None) -> str:
    """Target-syntax help body in the render locale (V2-escaped)."""
    return t("common.target.syntax", locale, plain=False)


def err_cannot_resolve(locale: str | None = None, *, plain: bool) -> str:
    """Cannot-resolve-target notice in the render locale."""
    return t("common.err.cannot_resolve", locale, plain=plain)


# ─────────────────────── Role / Auth Errors ─────────────────────── #


def err_role_verify(locale: str | None = None, *, plain: bool) -> str:
    """Group-role verification failure notice in the render locale."""
    return t("common.err.role_verify", locale, plain=plain)


def err_group_only(locale: str | None = None, *, plain: bool) -> str:
    """Group-only command refusal in the render locale."""
    return t("common.err.group_only", locale, plain=plain)


def err_no_connected_groups(locale: str | None = None, *, plain: bool) -> str:
    """Empty federation notice in the render locale."""
    return t("common.err.no_connected_groups", locale, plain=plain)


def err_group_not_found(locale: str | None = None, *, plain: bool) -> str:
    """Unknown-group notice in the render locale."""
    return t("common.err.group_not_found", locale, plain=plain)


def err_perm_expired(locale: str | None = None, *, plain: bool) -> str:
    """Expired-permission notice in the render locale."""
    return t("common.err.perm_expired", locale, plain=plain)


def err_unknown_role(locale: str | None = None, *, plain: bool) -> str:
    """Unknown-role notice in the render locale."""
    return t("common.err.unknown_role", locale, plain=plain)


# ───────────────────────── Server Errors ────────────────────────── #


def err_groups_load_failed(locale: str | None = None, *, plain: bool) -> str:
    """Group-list load failure notice in the render locale."""
    return t("common.err.groups_load_failed", locale, plain=plain)


def err_db_retry(locale: str | None = None, *, plain: bool) -> str:
    """Database-unreachable retry notice in the render locale."""
    return t("common.err.db_retry", locale, plain=plain)


# ──────────────────────── Context / Scope ───────────────────────── #
# * V2-escaped bodies for help "Where" sections.


def context_bot_or_group(locale: str | None = None) -> str:
    """Bot-or-group scope body in the render locale."""
    return t("common.context.bot_or_group", locale, plain=False)


def context_exec_or_group(locale: str | None = None) -> str:
    """Exec-or-group scope body in the render locale."""
    return t("common.context.exec_or_group", locale, plain=False)


def context_anyone(locale: str | None = None) -> str:
    """Anyone scope body in the render locale."""
    return t("common.context.anyone", locale, plain=False)


def where_connected_group(locale: str | None = None) -> str:
    """Connected-group scope body in the render locale."""
    return t("common.context.connected_group", locale, plain=False)


# ─────────────────────── Rate-limit replies ─────────────────────── #


def rate_limit_text(wait_s: float, locale: str | None = None, *, plain: bool) -> str:
    """Single owner for the user-facing rate-limit retry notice.

    Used by the global command/callback limiter and every per-handler
    ``ratelimiter`` rejection so throttled users always see the same
    wording regardless of which bucket stopped them. Clamped to a minimum
    of 1 second: sub-second waits would otherwise render as the confusing
    "try again in 0 seconds".
    """
    return t(
        "common.limit.text",
        locale,
        wait=max(1, round(wait_s)),
        plain=plain,
    )


# ─────────────────────── Permission Tiers ───────────────────────── #


def perm_founder_only(locale: str | None = None, *, plain: bool) -> str:
    """Founder-only refusal in the render locale."""
    return t("common.perm.founder_only", locale, plain=plain)


def perm_staff_only(locale: str | None = None, *, plain: bool) -> str:
    """Staff-only notice in the render locale."""
    return t("common.perm.staff_only", locale, plain=plain)


def perm_admin_above(locale: str | None = None, *, plain: bool) -> str:
    """Admin-and-above notice in the render locale."""
    return t("common.perm.admin_above", locale, plain=plain)


def perm_dev_above(locale: str | None = None, *, plain: bool) -> str:
    """Developer-and-above notice in the render locale."""
    return t("common.perm.dev_above", locale, plain=plain)


def perm_tester_above(locale: str | None = None, *, plain: bool) -> str:
    """Tester-and-above notice in the render locale."""
    return t("common.perm.tester_above", locale, plain=plain)


# ─────────────────────── Action Defaults ────────────────────────── #


def no_reason(locale: str | None = None, *, plain: bool) -> str:
    """Default reason text in the render locale."""
    return t("common.action.no_reason", locale, plain=plain)


# ────────────── Help-section header labels ───────────────────────── #
# * Raw labels: section buttons show them plain, section titles escape
# * them via bold().


def sec_commands(locale: str | None = None) -> str:
    """Commands section label in the render locale."""
    return t("common.section.commands", locale, plain=True)


def sec_who(locale: str | None = None) -> str:
    """Who section label in the render locale."""
    return t("common.section.who", locale, plain=True)


def sec_where(locale: str | None = None) -> str:
    """Where section label in the render locale."""
    return t("common.section.where", locale, plain=True)


def sec_what(locale: str | None = None) -> str:
    """Return the What section label in the render locale."""
    return t("common.section.what", locale, plain=True)


def sec_examples(locale: str | None = None) -> str:
    """Examples section label in the render locale."""
    return t("common.section.examples", locale, plain=True)


def sec_target(locale: str | None = None) -> str:
    """Target section label in the render locale."""
    return t("common.section.target", locale, plain=True)


# ─────────── Help-section constructor helpers ──────────────────── #


def who_section(perm: str, locale: str | None = None) -> tuple[str, str]:
    """Build a 'Who can use' section entry."""
    return (sec_who(locale), perm)


def where_section(ctx: str, locale: str | None = None) -> tuple[str, str]:
    """Build a 'Where to use' section entry."""
    return (sec_where(locale), ctx)


def target_section(locale: str | None = None) -> tuple[str, str]:
    """Build a standard 'Target syntax' section entry."""
    return (sec_target(locale), target_syntax(locale))
