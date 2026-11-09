# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared collection accessors for the groups database."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot.database.mongos import col

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection


def _groups() -> AsyncIOMotorCollection:
    return col("federated_groups")


def _pending() -> AsyncIOMotorCollection:
    return col("pending_joins")
