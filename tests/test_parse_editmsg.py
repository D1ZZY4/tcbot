# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.helper.parse_editmsg — safe_edit and safe_edit_cb."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from telegram.error import BadRequest

from tcbot.modules.helper.parse_editmsg import safe_edit, safe_edit_cb


def _make_message(side_effect=None) -> MagicMock:
    msg = MagicMock()
    if side_effect is None:
        msg.edit_text = AsyncMock()
    else:
        msg.edit_text = AsyncMock(side_effect=side_effect)
    return msg


def _make_callback_query(side_effect=None) -> MagicMock:
    q = MagicMock()
    if side_effect is None:
        q.edit_message_text = AsyncMock()
    else:
        q.edit_message_text = AsyncMock(side_effect=side_effect)
    return q


class TestSafeEdit:
    async def test_calls_edit_text_with_html_parse_mode(self):
        msg = _make_message()
        await safe_edit(msg, "Hello")
        msg.edit_text.assert_awaited_once_with("Hello", parse_mode="HTML")

    async def test_passes_extra_kwargs_to_edit_text(self):
        msg = _make_message()
        await safe_edit(msg, "text", reply_markup=None)
        msg.edit_text.assert_awaited_once_with(
            "text", parse_mode="HTML", reply_markup=None
        )

    async def test_swallows_message_not_modified(self):
        exc = BadRequest("Message is not modified")
        msg = _make_message(side_effect=exc)
        await safe_edit(msg, "same content")

    async def test_swallows_message_to_edit_not_found(self):
        exc = BadRequest("Message to edit not found")
        msg = _make_message(side_effect=exc)
        await safe_edit(msg, "text")

    async def test_swallows_chat_not_found(self):
        exc = BadRequest("Chat not found")
        msg = _make_message(side_effect=exc)
        await safe_edit(msg, "text")

    async def test_logs_unexpected_bad_request(self, caplog):
        exc = BadRequest("Some unexpected error")
        msg = _make_message(side_effect=exc)
        import logging

        with caplog.at_level(
            logging.WARNING, logger="tcbot.modules.helper.parse_editmsg"
        ):
            await safe_edit(msg, "text")
        assert any("edit failed" in r.message for r in caplog.records)

    async def test_does_not_suppress_unexpected_bad_request(self):
        exc = BadRequest("Some unexpected error")
        msg = _make_message(side_effect=exc)
        await safe_edit(msg, "text")


class TestSafeEditCb:
    async def test_calls_edit_message_text(self):
        q = _make_callback_query()
        await safe_edit_cb(q, "Hello")
        q.edit_message_text.assert_awaited_once_with("Hello", parse_mode="HTML")

    async def test_passes_extra_kwargs(self):
        q = _make_callback_query()
        await safe_edit_cb(q, "text", reply_markup=None)
        q.edit_message_text.assert_awaited_once_with(
            "text", parse_mode="HTML", reply_markup=None
        )

    async def test_swallows_message_not_modified(self):
        exc = BadRequest("Message is not modified")
        q = _make_callback_query(side_effect=exc)
        await safe_edit_cb(q, "same content")

    async def test_swallows_message_to_edit_not_found(self):
        exc = BadRequest("Message to edit not found")
        q = _make_callback_query(side_effect=exc)
        await safe_edit_cb(q, "text")

    async def test_swallows_chat_not_found(self):
        exc = BadRequest("Chat not found")
        q = _make_callback_query(side_effect=exc)
        await safe_edit_cb(q, "text")

    async def test_logs_unexpected_bad_request(self, caplog):
        exc = BadRequest("Completely different error")
        q = _make_callback_query(side_effect=exc)
        import logging

        with caplog.at_level(
            logging.WARNING, logger="tcbot.modules.helper.parse_editmsg"
        ):
            await safe_edit_cb(q, "text")
        assert any("callback edit failed" in r.message for r in caplog.records)
