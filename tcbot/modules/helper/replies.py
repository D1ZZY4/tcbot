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

TARGET_SYNTAX = (
    "Reply to a message, or provide a user ID / @username after the command\\."
)


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


# ──────────────────────── Context / Scope ───────────────────────── #

CONTEXT_BOT_OR_GROUP = "Bot PM, exec group, or any connected group\\."
CONTEXT_EXEC_OR_GROUP = "Exec group, any connected group, or bot PM\\."
CONTEXT_ANYONE = "Anyone, no special permissions needed\\."
WHERE_CONNECTED_GROUP = "Inside any connected group\\."

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
# * Locale-aware functions first; legacy V2-escaped constants below stay
# * for import-time help bodies until the help-label batch threads locale
# * through help rendering.


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


# ──────────────── Legacy Tier Constants (help bodies) ───────────── #

PERM_STAFF_ONLY = "TC Staff \\(Admin and above\\)\\."
PERM_ADMIN_ABOVE = "Admin and above \\(Founder / Admin\\)\\."
PERM_DEV_ABOVE = "Developer and above \\(Founder / Admin / Developer\\)\\."
PERM_TESTER_ABOVE = "Tester and above \\(Founder / Admin / Developer / Tester\\)\\."

# ─────────────────────── Action Defaults ────────────────────────── #


def no_reason(locale: str | None = None, *, plain: bool) -> str:
    """Default reason text in the render locale."""
    return t("common.action.no_reason", locale, plain=plain)


# ────────────── Help-section header labels ───────────────────────── #

SEC_COMMANDS = "Commands & Aliases"
SEC_WHO = "Who can use"
SEC_WHERE = "Where to use"
SEC_WHAT = "What it does"
SEC_EXAMPLES = "Examples"
SEC_TARGET = "Target syntax"


# ─────────── Help-section constructor helpers ──────────────────── #


def who_section(perm: str) -> tuple[str, str]:
    """Build a 'Who can use' section entry."""
    return (SEC_WHO, perm)


def where_section(ctx: str) -> tuple[str, str]:
    """Build a 'Where to use' section entry."""
    return (SEC_WHERE, ctx)


def target_section() -> tuple[str, str]:
    """Build a standard 'Target syntax' section entry."""
    return (SEC_TARGET, TARGET_SYNTAX)
