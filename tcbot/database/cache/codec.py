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

# * Exact types that require no recursive walk or key stringification.
_PRIMITIVE_TYPES: tuple[type, ...] = (str, int, float, bool, type(None))


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


_ENCODER: msgspec.json.Encoder = msgspec.json.Encoder(enc_hook=_msgspec_enc_hook)
_DECODER: msgspec.json.Decoder[Any] = msgspec.json.Decoder()


def _tag_scalars(value: Any) -> Any:
    """Replace ``datetime`` with a tagged JSON object before encoding.

    msgspec encodes ``datetime`` natively as a bare RFC3339 string, which
    would lose the tagged shape the L2 type contract requires, so tag first
    in Python and let msgspec encode the plain structure at C speed. The
    wire shape stays identical to the retired stdlib codec. Non-string
    mapping keys stringify like ``json.dumps`` does.
    """
    if type(value) in _PRIMITIVE_TYPES:
        return value
    if isinstance(value, datetime):
        return {_TYPE_KEY: _DATETIME_TYPE, "value": value.isoformat()}
    if isinstance(value, dict):
        # * Copy-on-write: skip allocating a new dict when every key is
        # * already a str and no value changed during tagging.
        new_dict: dict[str, Any] | None = None
        for k, v in value.items():
            sk = k if type(k) is str else (k if isinstance(k, str) else str(k))
            tv = _tag_scalars(v)
            if new_dict is not None:
                new_dict[sk] = tv
            elif sk is not k or tv is not v:
                # * Preserve original insertion order by rebuilding up to k.
                new_dict = {}
                for ek, ev in value.items():
                    if ek is k:
                        new_dict[sk] = tv
                        break
                    new_dict[ek if isinstance(ek, str) else str(ek)] = ev
        return new_dict if new_dict is not None else value
    if isinstance(value, list):
        new_list: list[Any] | None = None
        for idx, v in enumerate(value):
            tv = _tag_scalars(v)
            if new_list is not None:
                new_list.append(tv)
            elif tv is not v:
                new_list = value[:idx]
                new_list.append(tv)
        return new_list if new_list is not None else value
    if isinstance(value, tuple):
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
    if type(value) in _PRIMITIVE_TYPES:
        return value
    if isinstance(value, dict):
        restored = {k: _restore_tagged(v) for k, v in value.items()}
        if len(restored) == 2 and _TYPE_KEY in restored and "value" in restored:
            value_type = restored[_TYPE_KEY]
            raw_value = restored["value"]
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


def _restore_in_place(value: Any) -> Any:
    """Restore tagged datetimes in-place on a freshly decoded JSON graph."""
    if type(value) in _PRIMITIVE_TYPES:
        return value
    if isinstance(value, dict):
        for k, v in value.items():
            if type(v) not in _PRIMITIVE_TYPES:
                nv = _restore_in_place(v)
                if nv is not v:
                    value[k] = nv
        if (
            len(value) == 2
            and _TYPE_KEY in value
            and "value" in value
            and value[_TYPE_KEY] == _DATETIME_TYPE
        ):
            raw_value = value["value"]
            if isinstance(raw_value, str):
                try:
                    return datetime.fromisoformat(raw_value)
                except ValueError:
                    return value
        return value
    if isinstance(value, list):
        for idx, v in enumerate(value):
            if type(v) not in _PRIMITIVE_TYPES:
                nv = _restore_in_place(v)
                if nv is not v:
                    value[idx] = nv
        return value
    return value


def _encode_redis_value(value: Any) -> str:
    """Serialize one cache value to a UTF-8 JSON string via msgspec."""
    return _ENCODER.encode(_tag_scalars(value)).decode("utf-8")


def _decode_redis_value(raw: str | bytes) -> Any:
    """Deserialize one Redis string via msgspec, restoring tagged scalars."""
    return _restore_in_place(_DECODER.decode(raw))
