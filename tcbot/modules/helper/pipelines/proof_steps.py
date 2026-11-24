# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Proof-step infrastructure: media filter, keyboard, and prompts.

Evidence posting lives in :mod:`tcbot.modules.helper.pipelines.proof_post`;
import it there directly instead of through this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pyrogram import filters
from pyrogram.filters import Filter as BaseFilter
from pyrogram.types import InlineKeyboardMarkup

from tcbot.modules.helper.buttons import proof_step_btn
from tcbot.utils.i18n import Safe, bold, t
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


# ─────────────────────── Proof media filter ─────────────────────── #


# * Proof media shapes accepted everywhere: photos, videos, GIFs
# * (animations), and files. Voice notes, video notes, and stickers stay
# * rejected: they are not visual evidence. Single owner shared by every
# * proof receiver and unexpected-type handler so the two can never drift
# * apart within one conversation or across conversations.
PROOF_MEDIA_FILTER: BaseFilter = (
    filters.photo | filters.video | filters.animation | filters.document
)


# ─────────────────────────── BuildProof ─────────────────────────── #


@dataclass(frozen=True)
class BuildProof:
    """Configurable proof-step keyboard, prompts, and media recording."""

    action: str
    skip_allowed: bool = field(default=True, kw_only=True)

    def keyboard(self, locale: str | None = None) -> InlineKeyboardMarkup:
        """Proof-step keyboard: optional Skip, Done flush, Cancel.

        Done executes with everything collected so far (albums in one
        send and sequential sends alike); without it the ban path
        auto-flushes after a silence window instead. Markup lives in
        :func:`buttons.proof_step_btn`; this stays as a thin delegating
        step so existing call sites keep working.
        """
        return proof_step_btn(
            self.action, skip_allowed=self.skip_allowed, locale=locale
        )

    def _skip_hint(self, locale: str | None) -> Safe:
        if not self.skip_allowed:
            return Safe("")
        return Safe(
            t(
                "proof.hint.skip",
                locale,
                label=Safe(bold(t("button.skip", locale, plain=True))),
            )
        )

    def step_prompt(
        self,
        target_mention: str,
        action_label: str,
        reason: str,
        extra_info: str = "",
        locale: str | None = None,
    ) -> str:
        """Proof-step prompt after reason was collected in-conversation."""
        # * target_mention/extra_info must already be rich-markup-safe
        # * (mention/code output from the single mute.py producer).
        suffix = Safe(f" {extra_info}") if extra_info else Safe("")
        return t(
            "proof.prompt.step",
            locale,
            gerund=t(f"proof.action.{action_label}.doing", locale, plain=True),
            target=Safe(target_mention),
            suffix=suffix,
            reason=Safe(bold(reason)),
            done=t("button.done", locale, plain=True),
            skip_hint=self._skip_hint(locale),
        )

    def noted_prompt(
        self,
        action_label: str,
        inline_reason: str,
        target_mention: str,
        extra_info: str = "",
        locale: str | None = None,
    ) -> str:
        """Proof-step prompt when an inline reason was already provided."""
        # * Same rich-markup-safe contract as step_prompt above.
        suffix = Safe(f" {extra_info}") if extra_info else Safe("")
        return t(
            "proof.prompt.noted",
            locale,
            Doing=t(f"proof.action.{action_label}.Doing", locale, plain=True),
            target=Safe(target_mention),
            suffix=suffix,
            reason=Safe(bold(inline_reason)),
            done=t("button.done", locale, plain=True),
            skip_hint=self._skip_hint(locale),
        )
