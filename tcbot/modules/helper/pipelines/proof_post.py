# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Proof posting: classify media, upload evidence, and record landed items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

from pyrogram import Client
from pyrogram.types import InputMediaPhoto, InputMediaVideo, Message

from tcbot import cfg
from tcbot.modules.helper.messages.audit_logs import proof_caption_new
from tcbot.modules.helper.messages.links import message_link
from tcbot.modules.helper.rich.media import slideshow
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from tcbot.database.documents import EvidenceItemDoc, EvidenceMediaType

log = get_logger(__name__)


@dataclass(frozen=True)
class ProofItem:
    """One proof message that landed in the evidence destination."""

    media_type: str
    archive_message_id: int
    item_order: int
    file_unique_id: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    media_group_id: str | None = None
    duration_seconds: int | None = None
    width: int | None = None
    height: int | None = None
    file_name: str | None = None
    source_chat_id: int | None = None
    source_message_id: int | None = None
    caption_text: str | None = None

    def to_document(self) -> EvidenceItemDoc:
        """Return the row shape the evidence archive stores."""
        return {
            "media_type": cast("EvidenceMediaType", self.media_type),
            "archive_message_id": self.archive_message_id,
            "item_order": self.item_order,
            "media_group_id": self.media_group_id,
            "file_unique_id": self.file_unique_id,
            "mime_type": self.mime_type,
            "file_size_bytes": self.file_size_bytes,
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "file_name": self.file_name,
            "source_chat_id": self.source_chat_id,
            "source_message_id": self.source_message_id,
            "caption_text": self.caption_text,
        }


@dataclass(frozen=True)
class _SourceMedia:
    """A source message classified for upload and archive."""

    media_type: str
    send_kind: str
    file_id: str
    file_unique_id: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    duration_seconds: int | None = None
    width: int | None = None
    height: int | None = None
    file_name: str | None = None
    source_chat_id: int | None = None
    source_message_id: int | None = None
    caption_text: str | None = None


def _duration_seconds(value: int | timedelta | None) -> int | None:
    """Normalize a Kurigram media duration to whole seconds."""
    if isinstance(value, timedelta):
        return int(value.total_seconds())
    return value


def _source_media(message: Message) -> _SourceMedia | None:
    """Classify one proof message into the media it carries."""
    chat = getattr(message, "chat", None)
    source_chat_id = int(getattr(chat, "id", 0) or 0) or None
    source_message_id = int(getattr(message, "id", 0) or 0) or None
    caption = getattr(message, "caption", None)
    if message.photo:
        photo = message.photo
        return _SourceMedia(
            media_type="photo",
            send_kind="photo",
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            file_size_bytes=photo.file_size,
            width=photo.width,
            height=photo.height,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            caption_text=caption,
        )
    if message.video:
        video = message.video
        return _SourceMedia(
            media_type="video",
            send_kind="video",
            file_id=video.file_id,
            file_unique_id=video.file_unique_id,
            mime_type=video.mime_type,
            file_size_bytes=video.file_size,
            duration_seconds=_duration_seconds(video.duration),
            width=video.width,
            height=video.height,
            file_name=video.file_name,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            caption_text=caption,
        )
    if message.animation:
        animation = message.animation
        return _SourceMedia(
            media_type="animation",
            send_kind="animation",
            file_id=animation.file_id,
            file_unique_id=animation.file_unique_id,
            mime_type=animation.mime_type,
            file_size_bytes=animation.file_size,
            duration_seconds=_duration_seconds(animation.duration),
            width=animation.width,
            height=animation.height,
            file_name=animation.file_name,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            caption_text=caption,
        )
    if message.document:
        document = message.document
        return _SourceMedia(
            media_type="document",
            send_kind="document",
            file_id=document.file_id,
            file_unique_id=document.file_unique_id,
            mime_type=document.mime_type,
            file_size_bytes=document.file_size,
            file_name=document.file_name,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            caption_text=caption,
        )
    return None


def _landed_item(message: Message, source: _SourceMedia, order: int) -> ProofItem:
    """Describe one sent proof message with the metadata of its source."""
    return ProofItem(
        media_type=source.media_type,
        archive_message_id=int(message.id),
        item_order=order,
        file_unique_id=source.file_unique_id,
        mime_type=source.mime_type,
        file_size_bytes=source.file_size_bytes,
        media_group_id=getattr(message, "media_group_id", None),
        duration_seconds=source.duration_seconds,
        width=source.width,
        height=source.height,
        file_name=source.file_name,
        source_chat_id=source.source_chat_id,
        source_message_id=source.source_message_id,
        caption_text=source.caption_text or "",
    )


async def upload_proof_items(
    bot: Client,
    msgs: list[Message],
    caption: str,
    proof_chat: int,
    proof_thread: int | None,
) -> tuple[list[ProofItem], int]:
    """Upload proof media and return the landed items plus the source count.

    Photos and videos travel together in one media group (caption on the
    first item, per the Telegram API); animations and documents cannot join
    a media group, so each is sent individually after the gallery. The
    source count includes a file whose send failed, so the archive can mark
    a partial batch instead of claiming that a lost file landed. A failed
    gallery chunk is logged and skipped; a failed animation or document is
    logged and skipped so one bad file cannot void a good gallery.
    """
    sources = [source for msg in msgs if (source := _source_media(msg)) is not None]
    if not sources:
        return [], 0
    gallery = [source for source in sources if source.send_kind in ("photo", "video")]
    singles = [
        source for source in sources if source.send_kind not in ("photo", "video")
    ]
    landed: list[ProofItem] = []

    async def _send_single(source: _SourceMedia, cap: str | None) -> Message | None:
        if source.send_kind == "photo":
            return await bot.send_photo(
                proof_chat,
                source.file_id,
                caption=cap or "",
                parse_mode=None,
                message_thread_id=proof_thread,
            )
        if source.send_kind == "video":
            return await bot.send_video(
                proof_chat,
                source.file_id,
                caption=cap or "",
                parse_mode=None,
                message_thread_id=proof_thread,
            )
        if source.send_kind == "animation":
            return await bot.send_animation(
                proof_chat,
                source.file_id,
                caption=cap or "",
                parse_mode=None,
                message_thread_id=proof_thread,
            )
        return await bot.send_document(
            proof_chat,
            source.file_id,
            caption=cap,
            parse_mode=None,
            message_thread_id=proof_thread,
        )

    try:
        if gallery:
            if len(gallery) == 1:
                sent = await _send_single(gallery[0], caption)
                landed.append(_landed_item(sent, gallery[0], len(landed)))
                log.info(
                    "Proof media uploaded: message_id=%s",
                    landed[0].archive_message_id,
                )
                if not singles:
                    return landed, len(sources)
            else:
                # * Telegram caps a media group at 10 items; larger albums
                # * must be split or the whole gallery send is rejected.
                for chunk_start in range(0, len(gallery), 10):
                    chunk = gallery[chunk_start : chunk_start + 10]
                    media: list[Any] = [
                        InputMediaPhoto(
                            source.file_id,
                            # * Caption the first item that actually lands.
                            # * Keying it to chunk 0 would lose the caption
                            # * entirely when that chunk fails and a later
                            # * one is the first to reach the destination.
                            caption=(caption if not landed and index == 0 else "")
                            or "",
                            parse_mode=None,
                        )
                        if source.send_kind == "photo"
                        else InputMediaVideo(
                            source.file_id,
                            caption=(caption if not landed and index == 0 else "")
                            or "",
                            parse_mode=None,
                        )
                        for index, source in enumerate(chunk)
                    ]
                    try:
                        sent_group = await bot.send_media_group(
                            proof_chat, media, message_thread_id=proof_thread
                        )
                    except Exception:
                        log.exception("Proof gallery chunk upload failed")
                        continue
                    for sent, source in zip(sent_group, chunk, strict=False):
                        landed.append(_landed_item(sent, source, len(landed)))
                    if sent_group:
                        log.info(
                            "Proof gallery uploaded: %d items, message_id=%s",
                            len(sent_group),
                            landed[0].archive_message_id,
                        )
                if landed and not singles:
                    return landed, len(sources)
    except Exception:
        # * A gallery failure must not discard single media evidence: fall
        # * through to the single-item loop below.
        log.exception("Proof gallery upload failed; trying single media")
    # * The caption belongs to the first item that actually lands, not the
    # * first source in the list: a failed first send must not leave the landed
    # * evidence unlabelled. Track "already captioned" instead of the source
    # * index, which never advances back after a failure.
    caption_landed = bool(landed)
    for source in singles:
        try:
            sent = await _send_single(source, None if caption_landed else caption)
        except Exception:
            log.exception("Proof single media upload failed; continuing")
            continue
        caption_landed = True
        landed.append(_landed_item(sent, source, len(landed)))
    if landed and singles:
        log.info(
            "Proof single media uploaded alongside message_id=%s",
            landed[0].archive_message_id,
        )
    return landed, len(sources)


@dataclass(frozen=True)
class ProofUpload:
    """One uploaded proof: the landed items, the first id, and its link.

    ``items`` carries every message that actually reached the destination,
    in send order. ``expected_item_count`` is the number of source media the
    uploader tried to send, so a caller can archive a partial gallery
    honestly instead of treating the first message as the whole proof.
    """

    message_id: int | None = None
    link: str | None = None
    items: tuple[ProofItem, ...] = ()
    expected_item_count: int = 0
    slideshow_html: str = ""

    @property
    def landed(self) -> bool:
        """True when at least one proof message reached the channel."""
        return self.message_id is not None

    def documents(self) -> list[EvidenceItemDoc]:
        """Return the archived item rows for this upload."""
        return [item.to_document() for item in self.items]


async def upload_proof_media(
    bot: Client,
    msgs: list[Message],
    caption: str,
) -> ProofUpload:
    """Upload proof media with an explicit caption and build its link.

    Single owner for the "upload the proof and remember where it landed"
    step that the ban, kick, mute, and warn executors each ran. The
    destination comes from the configured proof channel, so a channel
    change lands in one place.

    A failed upload yields an empty :class:`ProofUpload` rather than
    raising: the moderation action is the important side effect, and a
    proof that could not be stored must not void it. The ban executor,
    which requires a proof, checks :attr:`ProofUpload.landed` itself.
    """
    if not msgs:
        return ProofUpload()
    proof_chat, proof_thread = cfg.proofs
    try:
        items, expected = await upload_proof_items(
            bot, msgs, caption, proof_chat, proof_thread
        )
    except Exception:
        log.exception("Proof upload failed")
        return ProofUpload()
    if not items:
        return ProofUpload(expected_item_count=expected)
    first = items[0]
    links = [
        message_link(proof_chat, item.archive_message_id, proof_thread)
        for item in items
    ]
    return ProofUpload(
        message_id=first.archive_message_id,
        link=message_link(proof_chat, first.archive_message_id, proof_thread),
        items=tuple(items),
        expected_item_count=expected,
        # * Existing rich media helper owns the presentation; no new code in rich/.
        slideshow_html=slideshow(links, caption=caption),
    )


async def upload_proof_for_action(
    bot: Client,
    msgs: list[Message],
    target_id: int,
    admin_id: int,
    admin_fname: str,
) -> ProofUpload:
    """Upload the proof media with the standard caption for an action.

    The caption names the target, the acting staff member, and the time.
    Only the ban executor uses a different caption (the re-ban caption
    carries the previous proof link), so it calls
    :func:`upload_proof_media` directly.
    """
    caption = proof_caption_new(target_id, admin_id, admin_fname, utc_now())
    return await upload_proof_media(bot, msgs, caption)
