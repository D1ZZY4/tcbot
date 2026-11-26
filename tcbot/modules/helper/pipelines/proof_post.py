# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Proof posting: classify media, upload evidence, and record landed items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

from pyrogram import Client
from pyrogram.types import (
    InputMediaAnimation,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    InputRichMessageMedia,
    Message,
)

from tcbot import cfg
from tcbot.modules.helper.messages.audit_logs import proof_caption_new
from tcbot.modules.helper.rich.block import html_message
from tcbot.modules.helper.rich.link import message_link
from tcbot.modules.helper.rich.media import slideshow
from tcbot.modules.helper.rich.send_msg import send_rich
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


# * A rich message accepts at most 50 attached media objects. A larger album
# * is split into several slideshows instead of losing its excess files.
_MAX_SLIDESHOW_MEDIA = 50


def _attached_media(source: _SourceMedia, media_id: str) -> InputRichMessageMedia:
    """Wrap one classified file for embedding in a rich slideshow."""
    if source.send_kind == "photo":
        content: Any = InputMediaPhoto(source.file_id)
    elif source.send_kind == "video":
        content = InputMediaVideo(source.file_id)
    elif source.send_kind == "animation":
        content = InputMediaAnimation(source.file_id)
    else:
        content = InputMediaDocument(source.file_id)
    return InputRichMessageMedia(id=media_id, media=content)


def _slideshow_item(
    message: Message,
    chunk: list[_SourceMedia],
    order: int,
    cap: str | None,
) -> ProofItem:
    """Describe the rich slideshow message that landed in the archive."""
    source = chunk[0]
    return ProofItem(
        media_type=source.media_type,
        archive_message_id=int(message.id),
        item_order=order,
        file_unique_id=source.file_unique_id,
        mime_type=source.mime_type,
        file_size_bytes=source.file_size_bytes,
        duration_seconds=source.duration_seconds,
        width=source.width,
        height=source.height,
        file_name=source.file_name,
        source_chat_id=source.source_chat_id,
        source_message_id=source.source_message_id,
        caption_text=cap or source.caption_text or "",
    )


async def upload_proof_items(
    bot: Client,
    msgs: list[Message],
    caption: str,
    proof_chat: int,
    proof_thread: int | None,
) -> tuple[list[ProofItem], int]:
    """Upload proof as rich slideshows with embedded media.

    Every landed artifact is one rich message carrying a slideshow; there is
    no plain media send and no alternate transport. The returned count is the
    number of rich messages attempted, so a lost chunk is recorded as partial
    rather than silently omitted.
    """
    sources = [source for msg in msgs if (source := _source_media(msg)) is not None]
    if not sources:
        return [], 0
    # * One slideshow holds one media kind. Mixing img, video, and
    # * document-backed items in one block is not a documented shape, so each
    # * kind gets its own rich message instead of risking a server refusal.
    chunks: list[list[_SourceMedia]] = []
    for kind in ("photo", "video", "animation", "document"):
        same_kind = [source for source in sources if source.send_kind == kind]
        chunks.extend(
            same_kind[start : start + _MAX_SLIDESHOW_MEDIA]
            for start in range(0, len(same_kind), _MAX_SLIDESHOW_MEDIA)
        )
    landed: list[ProofItem] = []
    for chunk in chunks:
        references: list[tuple[str, str]] = []
        attached: list[InputRichMessageMedia] = []
        for index, source in enumerate(chunk):
            media_id = f"m{index}"
            references.append((media_id, source.send_kind))
            attached.append(_attached_media(source, media_id))
        cap = caption
        # * The metadata is a compact rich table, not a figcaption: Telegram
        # * captions only accept inline text. The table follows the slideshow
        # * as its own block in the same rich message.
        html = f"{slideshow(references)}\n{cap}" if cap else slideshow(references)
        try:
            sent = await send_rich(
                bot,
                proof_chat,
                html_message(html, media=attached),
                message_thread_id=proof_thread,
            )
        except Exception:
            log.exception("Proof slideshow upload failed")
            continue
        landed.append(_slideshow_item(sent, chunk, len(landed), cap))
        log.info("Proof slideshow uploaded: message_id=%s", sent.id)
    return landed, len(chunks)


@dataclass(frozen=True)
class ProofUpload:
    """One uploaded proof: the landed items, the first id, and its link.

    ``items`` carries every rich slideshow that reached the destination, in
    send order. ``expected_item_count`` is the number of slideshows attempted,
    so a caller can archive a partial batch honestly instead of treating the
    first message as the whole proof.
    """

    message_id: int | None = None
    link: str | None = None
    items: tuple[ProofItem, ...] = ()
    expected_item_count: int = 0

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
    return ProofUpload(
        message_id=first.archive_message_id,
        link=message_link(proof_chat, first.archive_message_id, proof_thread),
        items=tuple(items),
        expected_item_count=expected,
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
