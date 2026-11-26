# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Proof upload sends one rich slideshow and never a plain media message."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pyrogram import Client
from pyrogram.types import (
    InputMediaAnimation,
    InputMediaDocument,
    InputMediaVideo,
    Message,
)

from tcbot.modules.helper.pipelines import proof_post


def _sent(message_id: int, **kwargs: Any) -> Any:
    """Build a Kurigram-shaped sent-message double."""
    return SimpleNamespace(id=message_id, message_id=message_id, **kwargs)


def _photo_message(file_id: str, message_id: int) -> Message:
    size = SimpleNamespace(
        file_id=file_id,
        file_unique_id=f"u-{file_id}",
        file_size=1234,
        width=800,
        height=600,
    )
    return cast(
        "Message",
        SimpleNamespace(
            photo=size,
            video=None,
            animation=None,
            document=None,
            caption=None,
            chat=SimpleNamespace(id=5),
            id=message_id,
            message_id=message_id,
        ),
    )


def _video_message(file_id: str, message_id: int) -> Message:
    return cast(
        "Message",
        SimpleNamespace(
            photo=None,
            video=SimpleNamespace(
                file_id=file_id,
                file_unique_id=f"u-{file_id}",
                mime_type="video/mp4",
                file_size=9999,
                duration=7,
                width=1280,
                height=720,
                file_name="clip.mp4",
            ),
            animation=None,
            document=None,
            caption="clip",
            chat=SimpleNamespace(id=5),
            id=message_id,
            message_id=message_id,
        ),
    )


def _document_message(file_id: str, message_id: int) -> Message:
    return cast(
        "Message",
        SimpleNamespace(
            photo=None,
            video=None,
            animation=None,
            document=SimpleNamespace(
                file_id=file_id,
                file_unique_id=f"u-{file_id}",
                mime_type="application/pdf",
                file_size=444,
                file_name="evidence.pdf",
            ),
            caption=None,
            chat=SimpleNamespace(id=5),
            id=message_id,
            message_id=message_id,
        ),
    )


def _animation_message(file_id: str, message_id: int) -> Message:
    return cast(
        "Message",
        SimpleNamespace(
            photo=None,
            video=None,
            animation=SimpleNamespace(
                file_id=file_id,
                file_unique_id=f"u-{file_id}",
                mime_type="video/mp4",
                file_size=777,
                duration=3,
                width=320,
                height=240,
                file_name="loop.mp4",
            ),
            document=None,
            caption="gif",
            chat=SimpleNamespace(id=5),
            id=message_id,
            message_id=message_id,
        ),
    )


class _RichBot:
    """Accept rich sends only; any plain media send is a regression."""

    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls: list[tuple[int | str, Any, dict[str, Any]]] = []
        self.fail_on_call = fail_on_call

    async def send_rich_message(
        self, chat_id: int | str, rich_message: Any, **kwargs: Any
    ) -> Any:
        self.calls.append((chat_id, rich_message, kwargs))
        if len(self.calls) == self.fail_on_call:
            raise RuntimeError("flood wait")
        return _sent(100 + len(self.calls))

    async def send_photo(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("proof must never use a plain photo send")

    async def send_video(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("proof must never use a plain video send")

    async def send_animation(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("proof must never use a plain animation send")

    async def send_document(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("proof must never use a plain document send")

    async def send_media_group(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("proof must never use a plain media group")


async def _upload(bot: _RichBot, messages: list[Message]) -> tuple[Any, int]:
    """Run the uploader through its public owner."""
    return await proof_post.upload_proof_items(
        cast("Client", bot), messages, "cap", -100, None
    )


def test_each_media_kind_gets_its_own_rich_slideshow() -> None:
    """Mixed kinds are split so Telegram never sees an undocumented block."""
    bot = _RichBot()
    items, expected = asyncio.run(
        _upload(
            bot,
            [
                _photo_message("p1", 1),
                _video_message("v1", 2),
                _animation_message("a1", 3),
                _document_message("d1", 4),
            ],
        )
    )

    assert expected == 4
    assert len(bot.calls) == 4
    htmls = [call[1].html for call in bot.calls]
    assert 'src="tg://photo?id=m0"' in htmls[0]
    assert 'src="tg://video?id=m0"' in htmls[1]
    assert 'src="tg://document?id=m0"' in htmls[2]
    assert 'src="tg://document?id=m0"' in htmls[3]
    assert all(html.endswith("</tg-slideshow>\ncap") for html in htmls)
    assert isinstance(bot.calls[1][1].media[0].media, InputMediaVideo)
    assert isinstance(bot.calls[2][1].media[0].media, InputMediaAnimation)
    assert isinstance(bot.calls[3][1].media[0].media, InputMediaDocument)
    assert len(items) == 4
    assert [item.archive_message_id for item in items] == [101, 102, 103, 104]
    assert [item.item_order for item in items] == [0, 1, 2, 3]
    assert all(item.caption_text == "cap" for item in items)


def test_a_video_keeps_its_media_type_and_duration() -> None:
    """The archived row still describes the first embedded file accurately."""
    bot = _RichBot()
    items, expected = asyncio.run(_upload(bot, [_video_message("v1", 7)]))

    assert expected == 1
    assert items[0].media_type == "video"
    assert items[0].duration_seconds == 7
    assert items[0].mime_type == "video/mp4"
    assert items[0].source_chat_id == 5
    assert items[0].source_message_id == 7


def test_an_oversized_album_is_split_into_more_slideshows() -> None:
    """The 50-media rich limit is respected without dropping evidence."""
    bot = _RichBot()
    messages = [_photo_message(f"p{i}", i) for i in range(51)]
    items, expected = asyncio.run(_upload(bot, messages))

    assert expected == 2
    assert len(bot.calls) == 2
    assert len(items) == 2
    assert [item.item_order for item in items] == [0, 1]
    first_html = bot.calls[0][1].html
    second_html = bot.calls[1][1].html
    assert 'src="tg://photo?id=m49"' in first_html
    assert 'src="tg://photo?id=m0"' in second_html
    assert first_html.endswith("</tg-slideshow>\ncap")
    assert second_html.endswith("</tg-slideshow>\ncap")


def test_a_failed_slideshow_is_recorded_as_partial() -> None:
    """A lost rich chunk must not be reported as a complete proof."""
    bot = _RichBot(fail_on_call=1)
    messages = [_photo_message(f"p{i}", i) for i in range(51)]
    items, expected = asyncio.run(_upload(bot, messages))

    assert expected == 2
    assert len(items) == 1
    assert items[0].caption_text == "cap"


def test_proof_metadata_table_follows_the_slideshow_as_a_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real proof message carries the metadata table outside figcaption."""
    monkeypatch.setattr(
        proof_post, "cfg", SimpleNamespace(proofs=(-1001234567890, None)), raising=False
    )
    bot = _RichBot()
    upload = asyncio.run(
        proof_post.upload_proof_for_action(
            cast("Client", bot),
            [_photo_message("p1", 1)],
            42,
            7,
            "Dizzy",
        )
    )

    html = bot.calls[0][1].html
    assert "</tg-slideshow>\n<table bordered striped compact>" in html
    assert "<figcaption>" not in html
    assert "<td><b>Admin</b></td><td>Dizzy</td>" in html
    assert upload.landed is True


def test_no_media_returns_an_empty_upload() -> None:
    """A text-only batch cannot produce a proof slideshow."""
    bot = _RichBot()
    items, expected = asyncio.run(_upload(bot, []))

    assert items == []
    assert expected == 0
    assert bot.calls == []


def test_upload_proof_media_uses_configured_destination_and_builds_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public wrapper owns the destination, link, and landed contract."""
    monkeypatch.setattr(
        proof_post, "cfg", SimpleNamespace(proofs=(-1001234567890, 7)), raising=False
    )
    bot = _RichBot()

    upload = asyncio.run(
        proof_post.upload_proof_media(
            cast("Client", bot),
            [_photo_message("p1", 1), _photo_message("p2", 2)],
            "cap",
        )
    )

    assert bot.calls[0][0] == -1001234567890
    assert bot.calls[0][2]["message_thread_id"] == 7
    assert upload.message_id == 101
    assert upload.link == "https://t.me/c/1234567890/101?thread=7"
    assert upload.landed is True
    assert upload.expected_item_count == 1
    assert len(upload.items) == 1
    assert len(upload.documents()) == 1
    assert upload.items[0].caption_text == "cap"


def test_upload_proof_media_without_media_does_not_contact_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        proof_post, "cfg", SimpleNamespace(proofs=(-100, 7)), raising=False
    )
    bot = _RichBot()

    upload = asyncio.run(proof_post.upload_proof_media(cast("Client", bot), [], "cap"))

    assert upload.landed is False
    assert upload.expected_item_count == 0
    assert upload.documents() == []
    assert bot.calls == []
