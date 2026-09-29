# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Tagged JSON codec preserving MongoDB scalars across the Redis boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import msgspec
from bson import ObjectId

_MONGO_TYPE_KEY: str = "__tcbot_type__"
_MONGO_DATETIME_TYPE: str = "datetime"
_MONGO_OBJECT_ID_TYPE: str = "objectid"


def _msgspec_enc_hook(obj: Any) -> Any:
    """Fallback encoder for scalar types msgspec cannot handle natively.

    Mirrors the retired stdlib ``default()`` fallback: unknown values become
    strings rather than failing the write. ``datetime`` and ``ObjectId``
    never reach this hook (see :func:`_tag_scalars`); it only covers
    genuinely unexpected scalars.
    """
    try:
        return str(obj)
    except Exception:
        raise TypeError(
            f"Object of type {type(obj).__name__} is not JSON serializable"
        ) from None


def _tag_scalars(value: Any) -> Any:
    """Replace ``datetime``/``ObjectId`` with tagged JSON objects before encoding.

    msgspec encodes ``datetime`` natively as a bare RFC3339 string, which
    would lose the tagged shape the L2 type contract requires, so tag first
    in Python and let msgspec encode the plain structure at C speed. The
    wire shape stays identical to the retired stdlib codec. Non-string
    mapping keys stringify like ``json.dumps`` does.
    """
    if isinstance(value, datetime):
        return {_MONGO_TYPE_KEY: _MONGO_DATETIME_TYPE, "value": value.isoformat()}
    if isinstance(value, ObjectId):
        return {_MONGO_TYPE_KEY: _MONGO_OBJECT_ID_TYPE, "value": str(value)}
    if isinstance(value, dict):
        return {
            (k if isinstance(k, str) else str(k)): _tag_scalars(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_tag_scalars(v) for v in value]
    return value


def _restore_tagged(value: Any) -> Any:
    """Restore tagged MongoDB scalar values while tolerating legacy cache data.

    Bottom-up replay of the retired stdlib ``object_hook``: children restore
    first, then the exact-shape check runs on the parent, so payloads written
    by either codec decode identically. Only exact-shape mappings (exactly
    the tag key plus the value key) restore: a user-controlled dict that
    merely contains the tag key must never deserialize into a datetime or
    ObjectId.
    """
    if isinstance(value, dict):
        restored = {k: _restore_tagged(v) for k, v in value.items()}
        if set(restored.keys()) != {_MONGO_TYPE_KEY, "value"}:
            return restored
        value_type = restored.get(_MONGO_TYPE_KEY)
        raw_value = restored.get("value")
        if value_type == _MONGO_DATETIME_TYPE and isinstance(raw_value, str):
            try:
                return datetime.fromisoformat(raw_value)
            except ValueError:
                return restored
        if value_type == _MONGO_OBJECT_ID_TYPE and isinstance(raw_value, str):
            try:
                return ObjectId(raw_value)
            except Exception:
                return restored
        return restored
    if isinstance(value, list):
        return [_restore_tagged(v) for v in value]
    return value


def _decode_redis_value(raw: str) -> Any:
    """Deserialize one Redis string via msgspec, restoring tagged scalars."""
    return _restore_tagged(msgspec.json.decode(raw))
