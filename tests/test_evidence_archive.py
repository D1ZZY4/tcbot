# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The evidence archive records the media that actually landed."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from tcbot import cfg
from tcbot.database import bans_db, kicks_db, mutes_db, warns_db
from tcbot.database import engine as engine_module
from tcbot.database.base import (
    moderation_actions,
    moderation_evidence_items,
    moderation_evidence_uploads,
)
from tests.postgres_support import (
    reset_community,
    seed_chats,
    seed_users,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def archive_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from one group, one proof channel, and one actor."""
    await reset_community()
    await seed_users(7)
    await seed_chats(-1001, cfg.proofs[0])
    yield postgres_db
    await reset_community()


async def _archive_of(ban_id: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    action = await engine_module.fetch_one(
        select(
            moderation_actions.c.evidence_upload_id,
        ).where(moderation_actions.c.external_ref == ban_id)
    )
    assert action is not None
    upload_id = int(action["evidence_upload_id"])
    upload = await engine_module.fetch_one(
        select(
            moderation_evidence_uploads.c.status,
            moderation_evidence_uploads.c.expected_item_count,
            moderation_evidence_uploads.c.primary_message_id,
        ).where(moderation_evidence_uploads.c.id == upload_id)
    )
    assert upload is not None
    items = await engine_module.fetch_all(
        select(
            moderation_evidence_items.c.media_type,
            moderation_evidence_items.c.archive_message_id,
            moderation_evidence_items.c.item_order,
            moderation_evidence_items.c.file_name,
        )
        .where(moderation_evidence_items.c.upload_id == upload_id)
        .order_by(moderation_evidence_items.c.item_order)
    )
    return upload, items


async def _archive_by_action_id(
    action_id: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    action = await engine_module.fetch_one(
        select(moderation_actions.c.evidence_upload_id).where(
            moderation_actions.c.id == action_id
        )
    )
    assert action is not None
    upload_id = int(action["evidence_upload_id"])
    upload = await engine_module.fetch_one(
        select(
            moderation_evidence_uploads.c.status,
            moderation_evidence_uploads.c.expected_item_count,
            moderation_evidence_uploads.c.is_required,
        ).where(moderation_evidence_uploads.c.id == upload_id)
    )
    assert upload is not None
    items = await engine_module.fetch_all(
        select(
            moderation_evidence_items.c.media_type,
            moderation_evidence_items.c.archive_message_id,
        )
        .where(moderation_evidence_items.c.upload_id == upload_id)
        .order_by(moderation_evidence_items.c.item_order)
    )
    return upload, items


async def test_a_kick_archives_its_optional_proof(archive_db: str) -> None:
    action_id = await kicks_db.log_kick(
        44,
        -1001,
        "spam",
        7,
        proof_items=[{"media_type": "video", "archive_message_id": 701}],
        proof_expected_count=1,
        destination_chat_id=cfg.proofs[0],
    )

    upload, items = await _archive_by_action_id(action_id)

    assert upload["status"] == "completed"
    assert upload["is_required"] is False
    assert items == [{"media_type": "video", "archive_message_id": 701}]


async def test_a_mute_archives_its_optional_proof(archive_db: str) -> None:
    action_id, _ = await mutes_db.record_mute(
        43,
        -1001,
        "spam",
        7,
        proof_items=[{"media_type": "photo", "archive_message_id": 711}],
        proof_expected_count=1,
        destination_chat_id=cfg.proofs[0],
    )

    upload, items = await _archive_by_action_id(action_id)

    assert upload["status"] == "completed"
    assert upload["is_required"] is False
    assert items == [{"media_type": "photo", "archive_message_id": 711}]


async def test_a_warn_archives_its_optional_proof(archive_db: str) -> None:
    await warns_db.add_warn(
        45,
        "spam",
        7,
        -1001,
        proof_items=[{"media_type": "document", "archive_message_id": 721}],
        proof_expected_count=1,
        destination_chat_id=cfg.proofs[0],
    )

    action = await engine_module.fetch_one(
        select(moderation_actions.c.id).where(
            moderation_actions.c.target_user_id == 45,
            moderation_actions.c.action_type == "warn",
        )
    )
    assert action is not None
    upload, items = await _archive_by_action_id(int(action["id"]))

    assert upload["status"] == "completed"
    assert upload["is_required"] is False
    assert items == [{"media_type": "document", "archive_message_id": 721}]


async def test_a_gallery_is_archived_as_every_item(archive_db: str) -> None:
    await bans_db.create_ban(
        42,
        "spam",
        7,
        501,
        0,
        "proofban001",
        destination_chat_id=cfg.proofs[0],
        proof_items=[
            {"media_type": "photo", "archive_message_id": 501},
            {"media_type": "video", "archive_message_id": 502, "width": 1280},
            {
                "media_type": "document",
                "archive_message_id": 503,
                "file_name": "evidence.pdf",
            },
        ],
        proof_expected_count=3,
    )

    upload, items = await _archive_of("proofban001")

    assert upload["status"] == "completed"
    assert upload["expected_item_count"] == 3
    assert upload["primary_message_id"] == 501
    assert [item["media_type"] for item in items] == [
        "photo",
        "video",
        "document",
    ]
    assert [item["archive_message_id"] for item in items] == [501, 502, 503]
    assert items[2]["file_name"] == "evidence.pdf"


async def test_a_reban_carries_every_previous_proof_item(archive_db: str) -> None:
    """A re-ban that keeps the old proof keeps its batch and media types."""
    await bans_db.create_ban(
        42,
        "spam",
        7,
        501,
        0,
        "proofban003",
        destination_chat_id=cfg.proofs[0],
        proof_items=[
            {"media_type": "photo", "archive_message_id": 501},
            {"media_type": "video", "archive_message_id": 502, "width": 1280},
        ],
        proof_expected_count=2,
    )
    current = await bans_db.get_ban("proofban003")
    assert current is not None
    old_proof = current.get("proof_message_id")
    assert old_proof

    updated = await bans_db.update_ban(
        "proofban003",
        "spam again",
        7,
        0,
        0,
        int(old_proof),
        0,
        destination_chat_id=cfg.proofs[0],
    )

    assert updated is not None
    new_ban_id = updated.get("ban_id")
    assert isinstance(new_ban_id, str)
    upload, items = await _archive_of(new_ban_id)
    assert upload["status"] == "completed"
    assert upload["expected_item_count"] == 2
    assert [item["media_type"] for item in items] == ["photo", "video"]
    assert [item["archive_message_id"] for item in items] == [501, 502]


async def test_a_reban_cannot_launder_a_partial_batch(archive_db: str) -> None:
    """A re-ban must not turn an incomplete proof into a completed batch."""
    await bans_db.create_ban(
        42,
        "spam",
        7,
        601,
        0,
        "proofban004",
        destination_chat_id=cfg.proofs[0],
        action_origin="automated",
        proof_items=[
            {"media_type": "photo", "archive_message_id": 601},
            {"media_type": "video", "archive_message_id": 602},
        ],
        proof_expected_count=3,
    )
    current = await bans_db.get_ban("proofban004")
    assert current is not None
    old_proof = current.get("proof_message_id")
    assert old_proof

    # * The manual re-ban keeps the partial batch and the schema refuses it:
    # * a manual decision may not stand on incomplete evidence. The error is
    # * the guarantee; silently recording the two items as complete is not.
    with pytest.raises(ProgrammingError, match="completed upload marked as required"):
        await bans_db.update_ban(
            "proofban004",
            "spam again",
            7,
            0,
            0,
            int(old_proof),
            0,
            destination_chat_id=cfg.proofs[0],
        )


async def test_a_lost_media_item_is_a_partial_upload(archive_db: str) -> None:
    await bans_db.create_ban(
        42,
        "spam",
        7,
        601,
        0,
        "proofban002",
        destination_chat_id=cfg.proofs[0],
        action_origin="automated",
        proof_items=[
            {"media_type": "photo", "archive_message_id": 601},
            {"media_type": "photo", "archive_message_id": 602},
        ],
        proof_expected_count=3,
    )

    upload, items = await _archive_of("proofban002")

    assert upload["status"] == "partial"
    assert upload["expected_item_count"] == 3
    assert len(items) == 2
    assert upload["primary_message_id"] == 601
