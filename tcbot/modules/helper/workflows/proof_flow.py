# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Proof-step infrastructure: keyboards, prompts, media recording, and channel upload."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from telegram.constants import KeyboardButtonStyle
from telegram.ext import filters
from telegram.ext.filters import BaseFilter

from tcbot.utils.formatter import bold

log = logging.getLogger(__name__)


# ─────────────────────── Proof media filter ─────────────────────── #


# * Proof media shapes accepted everywhere: photos, videos, GIFs
# * (animations), and files. Voice notes, video notes, and stickers stay
# * rejected: they are not visual evidence. Single owner shared by every
# * proof receiver and unexpected-type handler so the two can never drift
# * apart within a flow or across flows.
PROOF_MEDIA_FILTER: BaseFilter = (
    filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.Document.ALL
)


# ─────────────────────────── BuildProof ─────────────────────────── #


@dataclass(frozen=True)
class BuildProof:
    """Configurable proof-step keyboard, prompts, and media recording."""

    action: str
    skip_allowed: bool = field(default=True, kw_only=True)
    skip_label: str = field(default="Skip", kw_only=True)
    done_label: str = field(default="Done", kw_only=True)
    cancel_label: str = field(default="Cancel", kw_only=True)

    def keyboard(self) -> InlineKeyboardMarkup:
        """Proof-step keyboard: optional Skip, Done flush, Cancel.

        Done executes with everything collected so far (albums in one
        send and sequential sends alike); without it the ban path
        auto-flushes after a silence window instead.
        """
        buttons: list[InlineKeyboardButton] = []
        if self.skip_allowed:
            buttons.append(
                InlineKeyboardButton(
                    self.skip_label,
                    callback_data=f"{self.action}_skip_proof",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            )
        buttons.append(
            InlineKeyboardButton(
                self.done_label, callback_data=f"{self.action}_done_proof"
            )
        )
        buttons.append(
            InlineKeyboardButton(
                self.cancel_label, callback_data=f"{self.action}_cancel"
            )
        )
        return InlineKeyboardMarkup([buttons])

    def step_prompt(
        self,
        target_mention: str,
        action_label: str,
        reason: str,
        extra_info: str = "",
    ) -> str:
        """Proof-step prompt after reason was collected in-conversation."""
        suffix = f" {extra_info}" if extra_info else ""
        skip_hint = (
            f", or tap {bold(self.skip_label)} to proceed" if self.skip_allowed else ""
        )
        return (
            f"Reason noted; {action_label.lower()}ing {target_mention}{suffix}.\n"
            f"Reason: {bold(reason)}\n\n"
            f"Got any proof? Send photos, videos, GIFs, or files, then tap Done{skip_hint}."
        )

    def noted_prompt(
        self,
        action_label: str,
        inline_reason: str,
        target_mention: str,
        extra_info: str = "",
    ) -> str:
        """Proof-step prompt when an inline reason was already provided."""
        suffix = f" {extra_info}" if extra_info else ""
        skip_hint = (
            f", or tap {bold(self.skip_label)} to proceed" if self.skip_allowed else ""
        )
        return (
            f"{action_label.capitalize()}ing {target_mention}{suffix}.\n"
            f"Reason: {bold(inline_reason)}\n\n"
            f"Got any proof? Send photos, videos, GIFs, or files, then tap Done{skip_hint}."
        )

    @staticmethod
    def record(msg: Message) -> str | None:
        """Return a short proof description from a media message, or None."""
        if msg.photo:
            return f"Photo (msg {msg.message_id})"
        if msg.video:
            return f"Video (msg {msg.message_id})"
        if msg.animation:
            return f"GIF (msg {msg.message_id})"
        if msg.document:
            return f"File (msg {msg.message_id})"
        return None


# ───────────────────────── Channel upload ───────────────────────── #


async def upload_proof(
    bot: Bot,
    msgs: list[Message],
    caption: str,
    proof_chat: int,
    proof_thread: int | None,
) -> int | None:
    """Upload proof media to the proof channel. Returns proof_message_id or None.

    Photos and videos travel together in one media group (caption on the
    first item, per the Telegram API); animations and documents cannot join
    a media group, so each is sent individually after the gallery. The
    returned ID is the first message that landed, or None when nothing did.
    Gallery failures stay all-or-nothing like before; a failed document
    is logged and skipped so one bad file cannot void a good gallery.
    """
    # * Fast fail without Telegram I/O: empty input or a batch with no
    # * photo/video/animation/document item cannot produce an upload.
    # * Callers already guard on truthy proof_msgs, so this only bites on
    # * programming errors.
    if not msgs:
        return None
    # * Classify in arrival order; the caption always lands on the first
    # * message actually sent (gallery first, documents after), matching
    # * the old first-usable-item rule for every previously supported case.
    kinds: list[tuple[str, str]] = []
    for m in msgs:
        if m.photo:
            kinds.append(("photo", m.photo[-1].file_id))
        elif m.video:
            kinds.append(("video", m.video.file_id))
        elif m.animation:
            kinds.append(("document", m.animation.file_id))
        elif m.document:
            kinds.append(("document", m.document.file_id))
    if not kinds:
        return None
    gallery = [(k, f) for k, f in kinds if k in ("photo", "video")]
    docs = [f for k, f in kinds if k == "document"]

    async def _send_single(kind: str, file_id: str, cap: str | None) -> int:
        if kind == "photo":
            sent = await bot.send_photo(
                proof_chat,
                file_id,
                caption=cap,
                parse_mode="HTML",
                message_thread_id=proof_thread,
            )
        elif kind == "video":
            sent = await bot.send_video(
                proof_chat,
                file_id,
                caption=cap,
                parse_mode="HTML",
                message_thread_id=proof_thread,
            )
        else:
            sent = await bot.send_document(
                proof_chat,
                file_id,
                caption=cap,
                parse_mode="HTML",
                message_thread_id=proof_thread,
            )
        return sent.message_id

    first_id: int | None = None
    try:
        if gallery:
            if len(gallery) == 1:
                # * Unchanged single-photo/video send: a media group
                # * requires 2-10 items, so one item keeps its direct send.
                # * The gallery always goes first, so it owns the caption.
                kind, file_id = gallery[0]
                first_id = await _send_single(kind, file_id, caption)
                log.info("Proof photo uploaded: message_id=%s", first_id)
                if not docs:
                    return first_id
            else:
                media: list[InputMediaPhoto | InputMediaVideo] = [
                    InputMediaPhoto(
                        file_id,
                        caption=caption if idx == 0 else None,
                        parse_mode="HTML",
                    )
                    if kind == "photo"
                    else InputMediaVideo(
                        file_id,
                        caption=caption if idx == 0 else None,
                        parse_mode="HTML",
                    )
                    for idx, (kind, file_id) in enumerate(gallery)
                ]
                sent = await bot.send_media_group(
                    proof_chat, media, message_thread_id=proof_thread
                )
                if sent:
                    first_id = sent[0].message_id
                    log.info(
                        "Proof gallery uploaded: %d items, message_id=%s",
                        len(sent),
                        first_id,
                    )
                elif not docs:
                    return None
    except Exception:
        log.exception("Proof gallery upload failed")
        return None
    for idx, file_id in enumerate(docs):
        try:
            cap = caption if first_id is None and idx == 0 else None
            one_id = await _send_single("document", file_id, cap)
            if first_id is None:
                first_id = one_id
        except Exception:
            log.exception("Proof document upload failed; continuing with the rest")
    if first_id is None:
        return None
    if docs:
        log.info("Proof documents uploaded alongside message_id=%s", first_id)
    return first_id
