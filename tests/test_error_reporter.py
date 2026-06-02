# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.utils.error_reporter (pure functions, no Telegram connection)."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import telegram.error as _te

import tcbot.utils.error_reporter as er


@pytest.fixture(autouse=True)
def reset_reporter_state():
    er._bot = None
    er._chat_id = 0
    er._thread_id = None
    er._recent.clear()
    yield
    er._bot = None
    er._chat_id = 0
    er._thread_id = None
    er._recent.clear()


class TestAttach:
    def test_stores_bot_and_channel(self):
        fake_bot = MagicMock()
        er.attach(fake_bot, -1001, 5)
        assert er._bot is fake_bot
        assert er._chat_id == -1001
        assert er._thread_id == 5

    def test_thread_id_can_be_none(self):
        er.attach(MagicMock(), -1001, None)
        assert er._thread_id is None


class TestBenign:
    def test_none_exc_is_not_benign(self):
        assert er._benign(None) is False

    def test_message_not_modified_is_benign(self):
        exc = _te.BadRequest("Message is not modified")
        assert er._benign(exc) is True

    def test_message_to_edit_not_found_is_benign(self):
        exc = _te.BadRequest("Message to edit not found")
        assert er._benign(exc) is True

    def test_query_is_too_old_is_benign(self):
        exc = _te.BadRequest("Query is too old")
        assert er._benign(exc) is True

    def test_message_cant_be_edited_is_benign(self):
        exc = _te.BadRequest("Message can't be edited")
        assert er._benign(exc) is True

    def test_real_error_not_benign(self):
        exc = ValueError("real bug")
        assert er._benign(exc) is False

    def test_case_insensitive_match(self):
        exc = Exception("MESSAGE IS NOT MODIFIED")
        assert er._benign(exc) is True


class TestClassify:
    def test_none_returns_unknown(self):
        assert er._classify(None) == "[?] Unknown"

    def test_retry_after(self):
        exc = _te.RetryAfter(30)
        assert er._classify(exc) == "[~] Rate Limit: Flood Wait"

    def test_timed_out(self):
        exc = _te.TimedOut()
        assert er._classify(exc) == "[~] Telegram Timed Out"

    def test_bad_request(self):
        exc = _te.BadRequest("bad")
        assert er._classify(exc) == "[!] Telegram Bad Request"

    def test_forbidden(self):
        exc = _te.Forbidden("forbidden")
        assert er._classify(exc) == "[!] Telegram Forbidden"

    def test_network_error(self):
        exc = _te.NetworkError("network")
        assert er._classify(exc) == "[~] Telegram Network Error"

    def test_telegram_error_generic(self):
        exc = _te.TelegramError("generic")
        assert er._classify(exc) == "[!] Telegram API Error"

    def test_value_error_is_code_bug(self):
        exc = ValueError("oops")
        assert er._classify(exc) == "[!] Code Bug"

    def test_connection_error_is_network(self):
        exc = ConnectionError("refused")
        assert er._classify(exc) == "[~] Network / Server Error"


class TestShortenPath:
    def test_tcbot_path(self):
        result = er._shorten_path("/home/user/project/tcbot/modules/banning.py")
        assert result == "tcbot/modules/banning.py"

    def test_venv_site_packages_unix(self):
        result = er._shorten_path("/home/user/.venv/lib/python3.12/site-packages/telegram/bot.py")
        assert "telegram/bot.py" in result

    def test_bare_filename_fallback(self):
        result = er._shorten_path("/some/random/path/file.py")
        assert result == "file.py"

    def test_backslash_normalized(self):
        result = er._shorten_path("C:\\Users\\dev\\tcbot\\utils\\dispatch.py")
        assert "tcbot/utils/dispatch.py" in result


class TestLogNoise:
    def test_none_record_is_not_noise(self):
        assert er._log_noise(None) is False

    def test_raised_after_pattern_is_noise(self):
        record = logging.LogRecord(
            "test", logging.ERROR, "f.py", 1, " raised after something", (), None
        )
        assert er._log_noise(record) is True

    def test_normal_record_is_not_noise(self):
        record = logging.LogRecord(
            "test", logging.ERROR, "f.py", 1, "real error message", (), None
        )
        assert er._log_noise(record) is False


class TestBuildErrorMessage:
    def test_returns_string(self):
        result = er.build_error_message()
        assert isinstance(result, str)

    def test_contains_error_report_header(self):
        result = er.build_error_message()
        assert "Error Report" in result

    def test_contains_exception_type_for_exc(self):
        try:
            raise ValueError("test error")
        except ValueError as exc:
            result = er.build_error_message(exc=exc)
        assert "ValueError" in result

    def test_escapes_html_in_message(self):
        try:
            raise ValueError("<script>xss</script>")
        except ValueError as exc:
            result = er.build_error_message(exc=exc)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_context_included(self):
        result = er.build_error_message(context="ban_handler")
        assert "ban_handler" in result

    def test_code_bug_label_for_value_error(self):
        try:
            raise ValueError("oops")
        except ValueError as exc:
            result = er.build_error_message(exc=exc)
        assert "Code Bug" in result

    def test_record_message_included(self):
        record = logging.LogRecord(
            "mymodule", logging.ERROR, "file.py", 42, "something went wrong", (), None,
            func="test_function",
        )
        result = er.build_error_message(record=record)
        assert "something went wrong" in result


class TestSeenRecently:
    def test_first_occurrence_not_seen(self):
        fp = ("ValueError", "file.py", 10, "oops")
        assert er._seen_recently(fp) is False

    def test_second_occurrence_seen(self):
        fp = ("ValueError", "file.py", 10, "oops")
        er._seen_recently(fp)
        assert er._seen_recently(fp) is True

    def test_different_fingerprints_independent(self):
        fp1 = ("ValueError", "a.py", 1, "e1")
        fp2 = ("RuntimeError", "b.py", 2, "e2")
        er._seen_recently(fp1)
        assert er._seen_recently(fp2) is False


class TestSendToLogErrors:
    async def test_no_op_when_not_attached(self):
        await er.send_to_log_errors("test")

    async def test_no_op_when_chat_id_zero(self):
        er._bot = MagicMock()
        er._chat_id = 0
        await er.send_to_log_errors("test")

    async def test_calls_bot_send_message(self):
        fake_bot = AsyncMock()
        er._bot = fake_bot
        er._chat_id = -1001
        er._thread_id = None
        await er.send_to_log_errors("<b>Error</b>")
        fake_bot.send_message.assert_awaited_once()

    async def test_swallows_send_exception(self):
        fake_bot = AsyncMock(side_effect=Exception("network fail"))
        er._bot = fake_bot
        er._chat_id = -1001
        await er.send_to_log_errors("test")


class TestReportExc:
    async def test_skips_benign_exception(self):
        exc = _te.BadRequest("Message is not modified")
        with patch.object(er, "send_to_log_errors", new_callable=AsyncMock) as mock_send:
            await er.report_exc(exc)
            mock_send.assert_not_awaited()

    async def test_skips_duplicate_exception(self):
        try:
            raise ValueError("dup")
        except ValueError as exc:
            with patch.object(er, "send_to_log_errors", new_callable=AsyncMock) as mock_send:
                await er.report_exc(exc)
                await er.report_exc(exc)
                mock_send.assert_awaited_once()

    async def test_sends_real_exception(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            with patch.object(er, "send_to_log_errors", new_callable=AsyncMock) as mock_send:
                await er.report_exc(exc)
                mock_send.assert_awaited_once()


class TestReportRecord:
    async def test_skips_noise_records(self):
        record = logging.LogRecord(
            "test", logging.ERROR, "f.py", 1, " raised after handler", (), None
        )
        with patch.object(er, "send_to_log_errors", new_callable=AsyncMock) as mock_send:
            await er.report_record(record)
            mock_send.assert_not_awaited()

    async def test_sends_normal_records(self):
        record = logging.LogRecord(
            "test", logging.ERROR, "f.py", 1, "real error", (), None,
            func="some_handler",
        )
        with patch.object(er, "send_to_log_errors", new_callable=AsyncMock) as mock_send:
            await er.report_record(record)
            mock_send.assert_awaited_once()
