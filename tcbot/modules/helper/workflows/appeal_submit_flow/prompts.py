# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Instruction prompt text for appeal submissions."""

from __future__ import annotations

from tcbot.utils.formatter import pre
from tcbot.utils.i18n import t


def instruction_text(
    *, community_name: str, log_channel: str, locale: str | None
) -> str:
    """Render the multi-line MarkdownV2 instruction prompt."""
    log_handle = log_channel.lstrip("@")
    example = pre(
        t(
            "appeals.instruction.example_body",
            locale,
            logs=log_handle,
            plain=True,
        )
    )
    return (
        f"{t('appeals.instruction.title', locale, community=community_name)}\n\n"
        f"{t('appeals.instruction.intro', locale)}\n"
        f"{t('appeals.instruction.log_item', locale)}\n"
        f"{t('appeals.instruction.clarify_item', locale)}\n"
        f"{t('appeals.instruction.agree_item', locale)}\n\n"
        f"{t('appeals.instruction.example_label', locale)}\n"
        f"{example}\n\n"
        f"{t('appeals.instruction.channel', locale, handle=log_channel)}"
    )
