# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared MongoDB client kwargs: valid for Motor and never duplicated in connect()."""

from __future__ import annotations

import inspect

from motor.motor_asyncio import AsyncIOMotorClient

from tcbot.database import mongos


def test_shared_kwargs_cover_server_timeouts() -> None:
    kwargs = mongos.mongo_client_kwargs()

    assert kwargs["serverSelectionTimeoutMS"] == mongos._MONGO_SERVER_SELECTION_MS
    assert kwargs["connectTimeoutMS"] == mongos._MONGO_CONNECT_TIMEOUT_MS


def test_shared_kwargs_construct_motor_client() -> None:
    client = AsyncIOMotorClient(
        "mongodb://localhost:27017", **mongos.mongo_client_kwargs()
    )
    client.close()


def test_connect_does_not_repeat_shared_kwargs() -> None:
    """Guard the production startup crash: an explicit kwarg in connect()
    that is also inside mongo_client_kwargs() is a duplicate keyword
    argument and AsyncIOMotorClient raises TypeError at boot."""
    source = inspect.getsource(mongos.connect)
    call = source.split("AsyncIOMotorClient(")[1]
    for key in mongos.mongo_client_kwargs():
        assert f"{key}=" not in call
