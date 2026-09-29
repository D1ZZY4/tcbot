# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Configurable reason-step keyboard and prompt builder."""

from __future__ import annotations

from dataclasses import dataclass, field

from telegram import InlineKeyboardMarkup

from tcbot.modules.helper.keyboards import reason_step_kb
from tcbot.utils.formatter import bold
from tcbot.utils.i18n import Safe, t

# ─────────────────────────── BuildReason ────────────────────────── #


@dataclass(frozen=True)
class BuildReason:
    """Configurable reason-step keyboard and prompt builder."""

    action: str
    skip_allowed: bool = field(default=True, kw_only=True)

    def keyboard(self, locale: str | None = None) -> InlineKeyboardMarkup:
        """Reason-step keyboard. Includes Skip only when skip_allowed is True.

        Markup lives in :func:`keyboards.reason_step_kb`; this stays as a
        thin delegating step so existing call sites keep working.
        """
        return reason_step_kb(
            self.action, skip_allowed=self.skip_allowed, locale=locale
        )

    def prompt(
        self,
        target_mention: str,
        action_label: str,
        extra_info: str = "",
        locale: str | None = None,
    ) -> str:
        """Prompt asking the moderator to type a reason."""
        # * target_mention/extra_info must already be MarkdownV2-ready
        # * (mention/code/bold output): the single producer (muting.py
        # * code() ID plus fmt_duration) is verified, so no re-escaping here.
        suffix = Safe(f" {extra_info}") if extra_info else Safe("")
        skip_hint = (
            Safe("")
            if not self.skip_allowed
            else Safe(
                t(
                    "reason.hint.skip",
                    locale,
                    label=Safe(bold(t("button.skip", locale, plain=True))),
                )
            )
        )
        return t(
            "reason.prompt.body",
            locale,
            verb=t(f"proof.action.{action_label}.verb", locale, plain=True),
            target=Safe(target_mention),
            suffix=suffix,
            skip_hint=skip_hint,
        )
