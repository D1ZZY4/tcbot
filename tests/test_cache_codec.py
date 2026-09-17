# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Redis codec: tagged datetime/ObjectId values survive a msgspec round trip."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import msgspec
import pytest
from bson import ObjectId

from tcbot.database.cache import (
    _decode_redis_value,
    _msgspec_enc_hook,
    _tag_scalars,
)


def _legacy_encode(value: object) -> str:
    """Encode with the retired stdlib codec shape for back-compat vectors."""

    class _Old(json.JSONEncoder):
        def default(self, o: object) -> object:
            if isinstance(o, datetime):
                return {"__tcbot_type__": "datetime", "value": o.isoformat()}
            if isinstance(o, ObjectId):
                return {"__tcbot_type__": "objectid", "value": str(o)}
            return super().default(o)

    return json.dumps(value, cls=_Old)


def _new_encode(value: object) -> str:
    """Encode with the current msgspec codec."""
    return msgspec.json.encode(_tag_scalars(value), enc_hook=_msgspec_enc_hook).decode(
        "utf-8"
    )


def test_wire_shape_matches_legacy_codec() -> None:
    value = {
        "chat_id": -1001,
        "title": "G",
        "ts": datetime(2026, 9, 17, 12, 30, tzinfo=UTC),
        "oid": ObjectId("68cb0f1a2b3c4d5e6f708192"),
        "tags": ["a", None, 1, True],
    }
    assert json.loads(_new_encode(value)) == json.loads(_legacy_encode(value))


def test_decoded_types_match_across_codecs() -> None:
    value = {
        "ts": datetime(2026, 9, 17, 12, 30, tzinfo=UTC),
        "oid": ObjectId("68cb0f1a2b3c4d5e6f708192"),
        "nested": [{"ts": datetime(2026, 1, 1, tzinfo=UTC)}],
    }
    for raw in (_legacy_encode(value), _new_encode(value)):
        decoded = _decode_redis_value(raw)
        assert isinstance(decoded["ts"], datetime)
        assert isinstance(decoded["oid"], ObjectId)
        assert isinstance(decoded["nested"][0]["ts"], datetime)


def test_untagged_and_malformed_tags_stay_plain_data() -> None:
    assert _decode_redis_value('{"a": 1}') == {"a": 1}
    # * Tag key plus extra keys is not the exact shape: never restore.
    wide = {"__tcbot_type__": "datetime", "value": "2026-01-01", "extra": 1}
    assert _decode_redis_value(json.dumps(wide)) == wide
    # * Unparseable date stays a dict instead of raising.
    bad_date = {"__tcbot_type__": "datetime", "value": "not-a-date"}
    assert _decode_redis_value(json.dumps(bad_date)) == bad_date


def test_corrupt_payload_raises() -> None:
    with pytest.raises(msgspec.DecodeError):
        _decode_redis_value("{nope")
