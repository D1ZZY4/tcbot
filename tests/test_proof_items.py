# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Proof upload records every landed media item, not one photo placeholder."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from telegram import Bot, Message

from tcbot.modules.helper.pipelines import proof_steps


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
            photo=[size],
            video=None,
            animation=None,
            document=None,
            caption=None,
            chat=SimpleNamespace(id=5),
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
            message_id=message_id,
        ),
    )


def test_a_gallery_and_a_document_are_all_recorded() -> None:
    messages = [
        _photo_message("p1", 1),
        _photo_message("p2", 2),
        _document_message("d1", 3),
    ]
    sent_ids = iter(range(100, 200))

    class _Bot:
        async def send_media_group(self, *args: Any, **kwargs: Any) -> list[Any]:
            return [
                SimpleNamespace(message_id=next(sent_ids), media_group_id="g1"),
                SimpleNamespace(message_id=next(sent_ids), media_group_id="g1"),
            ]

        async def send_document(self, *args: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(message_id=next(sent_ids))

        async def send_photo(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a gallery must not fall back to single sends")

        async def send_video(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a gallery must not fall back to single sends")

    items, expected = asyncio.run(
        proof_steps.upload_proof_items(
            cast("Bot", _Bot()),
            messages,
            "cap",
            -100,
            None,  # type: ignore[arg-type]
        )
    )

    assert expected == 3
    assert [item.media_type for item in items] == ["photo", "photo", "document"]
    assert [item.item_order for item in items] == [0, 1, 2]
    assert [item.archive_message_id for item in items] == [100, 101, 102]
    assert items[2].file_name == "evidence.pdf"
    assert items[0].file_size_bytes == 1234


def test_a_video_keeps_its_media_type_and_duration() -> None:
    async def _send_video(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(message_id=55)

    bot = type("Bot", (), {"send_video": _send_video})()

    items, expected = asyncio.run(
        proof_steps.upload_proof_items(
            cast("Bot", bot),
            [_video_message("v1", 7)],
            "cap",
            -100,
            None,  # type: ignore[arg-type]
        )
    )

    assert expected == 1
    assert items[0].media_type == "video"
    assert items[0].duration_seconds == 7
    assert items[0].mime_type == "video/mp4"
    assert items[0].source_chat_id == 5
    assert items[0].source_message_id == 7


def test_a_failed_chunk_marks_the_upload_partial() -> None:
    messages = [_photo_message(f"p{i}", i) for i in range(11)]
    calls = 0

    class _Bot:
        async def send_media_group(self, *args: Any, **kwargs: Any) -> list[Any]:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("flood wait")
            return [SimpleNamespace(message_id=200 + i) for i in range(10)]

        async def send_photo(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a gallery must not fall back to single sends")

    items, expected = asyncio.run(
        proof_steps.upload_proof_items(
            cast("Bot", _Bot()),
            messages,
            "cap",
            -100,
            None,  # type: ignore[arg-type]
        )
    )

    assert expected == 11
    assert len(items) == 10
    assert [item.item_order for item in items] == list(range(10))


def test_caption_lands_on_the_first_chunk_that_succeeds() -> None:
    """A failed first chunk must not leave the archive without a caption."""
    messages = [_photo_message(f"p{i}", i) for i in range(11)]
    captured: list[list[Any]] = []
    calls = 0

    class _Bot:
        async def send_media_group(self, *args: Any, **kwargs: Any) -> list[Any]:
            nonlocal calls
            calls += 1
            captured.append(args[1])
            if calls == 1:
                raise RuntimeError("flood wait on first chunk")
            return [SimpleNamespace(message_id=300 + i) for i in range(len(args[1]))]

        async def send_photo(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a gallery must not fall back to single sends")

    items, expected = asyncio.run(
        proof_steps.upload_proof_items(
            cast("Bot", _Bot()),
            messages,
            "cap",
            -100,
            None,  # type: ignore[arg-type]
        )
    )

    assert expected == 11
    assert len(items) == 1
    assert captured[1][0].caption == "cap"
    assert all(item.caption is None for item in captured[1][1:])


def test_an_animation_is_sent_as_an_animation() -> None:
    """A GIF keeps its animation kind instead of becoming a document."""
    sent: list[tuple[str, str]] = []

    class _Bot:
        async def send_animation(self, *args: Any, **kwargs: Any) -> Any:
            sent.append(("animation", str(args[1])))
            return SimpleNamespace(message_id=61)

        async def send_document(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("an animation must not be sent as a document")

    items, expected = asyncio.run(
        proof_steps.upload_proof_items(
            cast("Bot", _Bot()),
            [_animation_message("a1", 8)],
            "cap",
            -100,
            None,  # type: ignore[arg-type]
        )
    )

    assert sent == [("animation", "a1")]
    assert expected == 1
    assert items[0].media_type == "animation"
    assert items[0].duration_seconds == 3
    assert items[0].file_name == "loop.mp4"


def test_a_gallery_and_an_animation_are_both_archived() -> None:
    """The gallery fast path must not drop a single media item beside it."""
    sent: list[tuple[str, str]] = []

    class _Bot:
        async def send_media_group(self, *args: Any, **kwargs: Any) -> list[Any]:
            return [
                SimpleNamespace(message_id=100, media_group_id="g1"),
                SimpleNamespace(message_id=101, media_group_id="g1"),
            ]

        async def send_animation(self, *args: Any, **kwargs: Any) -> Any:
            sent.append(("animation", str(args[1])))
            return SimpleNamespace(message_id=102)

        async def send_photo(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a gallery must not fall back to single sends")

    items, expected = asyncio.run(
        proof_steps.upload_proof_items(
            cast("Bot", _Bot()),
            [
                _photo_message("p1", 1),
                _photo_message("p2", 2),
                _animation_message("a1", 3),
            ],
            "cap",
            -100,
            None,  # type: ignore[arg-type]
        )
    )

    assert sent == [("animation", "a1")]
    assert expected == 3
    assert [item.media_type for item in items] == ["photo", "photo", "animation"]
    assert [item.item_order for item in items] == [0, 1, 2]
    assert [item.archive_message_id for item in items] == [100, 101, 102]
