# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for proof_flow: BuildProof pure helpers and upload_proof channel logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from tcbot.modules.helper.workflows.proof_flow import BuildProof, upload_proof

# ──────────────────────── BuildProof.keyboard ───────────────────── #


def test_build_proof_keyboard_with_skip_has_two_buttons() -> None:
    bp = BuildProof("ban", skip_allowed=True, skip_label="Skip")
    buttons = bp.keyboard().inline_keyboard[0]
    labels = [b.text for b in buttons]
    assert "Skip" in labels
    assert "Cancel" in labels
    assert len(buttons) == 2


def test_build_proof_keyboard_without_skip_has_one_button() -> None:
    bp = BuildProof("ban", skip_allowed=False)
    buttons = bp.keyboard().inline_keyboard[0]
    assert len(buttons) == 1
    assert buttons[0].text == "Cancel"


def test_build_proof_keyboard_callback_data_uses_action() -> None:
    bp = BuildProof("warn")
    buttons = bp.keyboard().inline_keyboard[0]
    cb_datas = {b.callback_data for b in buttons}
    assert "warn_skip_proof" in cb_datas
    assert "warn_cancel" in cb_datas


# ─────────────────────── BuildProof.step_prompt ─────────────────── #


def test_step_prompt_includes_skip_hint_when_allowed() -> None:
    bp = BuildProof("ban", skip_allowed=True, skip_label="Skip")
    p = bp.step_prompt("@Target", "ban", "spam")
    assert "Skip" in p
    assert "spam" in p
    assert "@Target" in p


def test_step_prompt_omits_skip_hint_when_not_allowed() -> None:
    bp = BuildProof("ban", skip_allowed=False)
    p = bp.step_prompt("@Target", "ban", "spam")
    assert "Skip" not in p


def test_step_prompt_includes_extra_info() -> None:
    bp = BuildProof("ban", skip_allowed=False)
    p = bp.step_prompt("@Target", "ban", "flood", extra_info="(third offence)")
    assert "(third offence)" in p


# ─────────────────────── BuildProof.noted_prompt ────────────────── #


def test_noted_prompt_includes_inline_reason() -> None:
    bp = BuildProof("kick", skip_allowed=True, skip_label="Skip")
    p = bp.noted_prompt("kick", "harassment", "@Target")
    assert "harassment" in p
    assert "Skip" in p


def test_noted_prompt_omits_skip_hint_when_not_allowed() -> None:
    bp = BuildProof("kick", skip_allowed=False)
    p = bp.noted_prompt("kick", "harassment", "@Target")
    assert "Skip" not in p


# ───────────────────────── BuildProof.record ────────────────────── #


def test_record_photo_message_returns_description() -> None:
    msg = SimpleNamespace(
        message_id=42, photo=[SimpleNamespace(file_id="abc")], video=None
    )
    result = BuildProof.record(msg)
    assert result == "Photo (msg 42)"


def test_record_video_message_returns_description() -> None:
    msg = SimpleNamespace(
        message_id=7, photo=None, video=SimpleNamespace(file_id="xyz")
    )
    result = BuildProof.record(msg)
    assert result == "Video (msg 7)"


def test_record_no_media_returns_none() -> None:
    msg = SimpleNamespace(message_id=1, photo=None, video=None)
    assert BuildProof.record(msg) is None


# ──────────────────────── upload_proof ──────────────────────────── #


async def test_upload_proof_single_photo_returns_message_id() -> None:
    bot = SimpleNamespace(
        send_photo=AsyncMock(return_value=SimpleNamespace(message_id=100))
    )
    msg = SimpleNamespace(
        photo=[SimpleNamespace(file_id="photo_fid")],
        video=None,
    )
    result = await upload_proof(bot, [msg], "caption", -1001, None)
    assert result == 100
    bot.send_photo.assert_awaited_once()


async def test_upload_proof_single_video_returns_message_id() -> None:
    bot = SimpleNamespace(
        send_video=AsyncMock(return_value=SimpleNamespace(message_id=200))
    )
    msg = SimpleNamespace(
        photo=None,
        video=SimpleNamespace(file_id="video_fid"),
    )
    result = await upload_proof(bot, [msg], "caption", -1001, None)
    assert result == 200
    bot.send_video.assert_awaited_once()


async def test_upload_proof_album_returns_first_message_id() -> None:
    bot = SimpleNamespace(
        send_media_group=AsyncMock(
            return_value=[
                SimpleNamespace(message_id=300),
                SimpleNamespace(message_id=301),
            ]
        )
    )
    msgs = [
        SimpleNamespace(photo=[SimpleNamespace(file_id="f1")], video=None),
        SimpleNamespace(photo=[SimpleNamespace(file_id="f2")], video=None),
    ]
    result = await upload_proof(bot, msgs, "caption", -1001, 5)
    assert result == 300
    bot.send_media_group.assert_awaited_once()
    call_kwargs = bot.send_media_group.await_args.kwargs
    assert call_kwargs.get("message_thread_id") == 5


async def test_upload_proof_failure_returns_none() -> None:
    bot = SimpleNamespace(
        send_photo=AsyncMock(side_effect=RuntimeError("network error"))
    )
    msg = SimpleNamespace(photo=[SimpleNamespace(file_id="f")], video=None)
    result = await upload_proof(bot, [msg], "caption", -1001, None)
    assert result is None
