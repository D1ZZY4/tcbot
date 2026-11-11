# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Tagged JSON codec preserving the datetimes that cross the Redis boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import msgspec

# * The tag key and the datetime tag value are part of the cached wire
# * format: they must stay byte-compatible with the entries already in
# * Redis, otherwise every cached row would be a miss after a deploy.
_TYPE_KEY: str = "__tcbot_type__"
_DATETIME_TYPE: str = "datetime"


def _msgspec_enc_hook(obj: Any) -> Any:
    """Fallback encoder for scalar types msgspec cannot handle natively.

    Unknown values become strings rather than failing the write. A
    ``datetime`` never reaches this hook (see :func:`_tag_scalars`); it
    only covers genuinely unexpected scalars.
    """
    try:
        return str(obj)
    except Exception:
        raise TypeError(
            f"Object of type {type(obj).__name__} is not JSON serializable"
        ) from None


def _tag_scalars(value: Any) -> Any:
    """Replace ``datetime`` with a tagged JSON object before encoding.

    msgspec encodes ``datetime`` natively as a bare RFC3339 string, which
    would lose the tagged shape the L2 type contract requires, so tag first
    in Python and let msgspec encode the plain structure at C speed. The
    wire shape stays identical to the retired stdlib codec. Non-string
    mapping keys stringify like ``json.dumps`` does.
    """
    if isinstance(value, datetime):
        return {_TYPE_KEY: _DATETIME_TYPE, "value": value.isoformat()}
    if isinstance(value, dict):
        return {
            (k if isinstance(k, str) else str(k)): _tag_scalars(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_tag_scalars(v) for v in value]
    return value


def _restore_tagged(value: Any) -> Any:
    """Restore tagged datetimes while tolerating legacy cache data.

    Bottom-up replay of the retired stdlib ``object_hook``: children restore
    first, then the exact-shape check runs on the parent, so payloads written
    by either codec decode identically. Only exact-shape mappings (exactly
    the tag key plus the value key) restore: a user-controlled dict that
    merely contains the tag key must never deserialize into a datetime.
    """
    if isinstance(value, dict):
        restored = {k: _restore_tagged(v) for k, v in value.items()}
        if set(restored.keys()) != {_TYPE_KEY, "value"}:
            return restored
        value_type = restored.get(_TYPE_KEY)
        raw_value = restored.get("value")
        if value_type == _DATETIME_TYPE and isinstance(raw_value, str):
            try:
                return datetime.fromisoformat(raw_value)
            except ValueError:
                return restored
        # * Any other tag is unknown to this codec and stays a plain
        # * mapping. The MongoDB-era ``objectid`` tag written before the
        # * PostgreSQL migration lands here: the value survives as a
        # * mapping and no consumer needs it any more.
        return restored
    if isinstance(value, list):
        return [_restore_tagged(v) for v in value]
    return value


def _decode_redis_value(raw: str) -> Any:
    """Deserialize one Redis string via msgspec, restoring tagged scalars."""
    return _restore_tagged(msgspec.json.decode(raw))
