# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Inline reason parsing and the shared reason length cap."""

from __future__ import annotations

from tcbot.utils.i18n import t

# * Maximum characters accepted for a moderation reason.
# * Telegram hard-caps messages at 4096 chars; action summaries include names,
# * IDs, and other metadata on top of the reason.  1000 chars is generous for
# * any real reason while guaranteeing the combined message stays under the cap.
# * Public name so command entries can fail fast on overlong inline reasons
# * without paying for target resolution or DB work first.
MAX_REASON_LEN: int = 1000


# ───────────────────────── Reason parsing ───────────────────────── #


def parse_inline_reason(
    args: list[str],
    *,
    has_explicit_target: bool,
    reply_target_id: int | None = None,
) -> str:
    """Extract any inline reason text from command arguments.

    With an explicit target the first token names the target, so the
    reason starts at ``args[1:]``. On the reply-retained path every arg is
    reason text, with one exception: a leading numeric token equal to
    ``reply_target_id`` is the target restated (e.g. reply + ``/tcb
    1419172317 spamming`` aimed at 1419172317), not reason content, so it
    is dropped. A leading numeric token naming anyone else stays in the
    reason, unless the entry resolved it as a verified override target
    (then the entry passes ``has_explicit_target=True``). Pass ``None``
    (the default) whenever the entry is not on the reply-retained path.
    """
    tokens = args[1:] if has_explicit_target else args
    if (
        reply_target_id is not None
        and not has_explicit_target
        and tokens
        and tokens[0].lstrip("-").isdigit()
        and int(tokens[0]) == reply_target_id
    ):
        tokens = tokens[1:]
    return " ".join(tokens).strip()


def is_reason_too_long(text: str) -> bool:
    """Return True when ``text`` exceeds the shared reason length cap."""
    return len(text) > MAX_REASON_LEN


def reason_too_long_text(actual_len: int, locale: str | None = None) -> str:
    """Single source of truth for the overlong-reason reply text."""
    return t(
        "reason.limit.text",
        locale,
        max=MAX_REASON_LEN,
        actual=actual_len,
        plain=True,
    )
