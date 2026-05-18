# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Shared reason-collection utilities.

This module provides stateless helpers that are reused across every
conversation that requires a reason step (kick, mute, warn).  The actual
conversation state machines live in their own ``*_conv.py`` files; only the
pure parsing and formatting logic lives here.

Placement decision
──────────────────
* ``reason_flow.py`` (this file) - generic, stateless helpers.
* ``kicking_conv.py`` / ``muting_conv.py`` / ``warning_conv.py`` - the PTB
  ConversationHandlers that orchestrate the full flows.
"""

from __future__ import annotations


## ── Reason parsing ─────────────────────────────────────────────────────────

def parse_inline_reason(
    args: list[str],
    has_explicit_target: bool,
) -> str:
    """Extract any inline reason text from command arguments.

    Args:
        args:                 Raw token list from :func:`parse_cmd_args`.
        has_explicit_target:  ``True`` when the first token was identified as a
            user reference (ID or @username) so it should be skipped.

    Returns:
        The joined reason string, or an empty string when no reason was given.

    Example::

        args = ["@user", "spamming", "in", "groups"]
        reason = parse_inline_reason(args, has_explicit_target=True)
        # → "spamming in groups"

        args = ["spamming", "in", "groups"]
        reason = parse_inline_reason(args, has_explicit_target=False)
        # → "spamming in groups"
    """
    tokens = args[1:] if has_explicit_target else args
    return " ".join(tokens).strip()


## ── Reason prompt helpers ──────────────────────────────────────────────────

def reason_prompt(target_mention: str, action_label: str) -> str:
    """Return the prompt message asking the moderator for a reason.

    Args:
        target_mention: HTML mention or plain name of the target user.
        action_label:   Human-readable action name, e.g. ``"kick"``, ``"mute"``.

    Returns:
        An HTML-formatted prompt string ready to send as a bot reply.

    Example::

        text = reason_prompt("<a href='...'>Alice</a>", "kick")
        # → "About to kick <a href='...'>Alice</a>.\\nWhat's the reason? ..."
    """
    return (
        f"About to {action_label} {target_mention}.\n"
        "What's the reason? Type it below, or tap <b>Skip</b>."
    )


def reason_noted_prompt(action_label: str, inline_reason: str, target_mention: str) -> str:
    """Return the proof-step prompt when an inline reason was already provided.

    Args:
        action_label:   Human-readable action name, e.g. ``"kick"``.
        inline_reason:  The reason text already captured from the command.
        target_mention: HTML mention or plain name of the target user.

    Returns:
        An HTML-formatted prompt string for the proof step.
    """
    return (
        f"{action_label.capitalize()}ing {target_mention}.\n"
        f"Reason: <b>{inline_reason}</b>\n\n"
        "Got any proof? Send a photo or video, or tap <b>Skip</b> to proceed."
    )
