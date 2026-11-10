# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Constant-time secret comparison for every inbound credential check."""

from __future__ import annotations

import hmac


def secret_matches(provided: str, expected: str) -> bool:
    """Return True when *provided* equals *expected*, compared in constant time.

    The comparison runs on UTF-8 bytes because ``hmac.compare_digest``
    rejects non-ASCII strings with a ``TypeError``. A credential header
    carrying a non-ASCII byte would therefore raise inside the request
    handler and surface as an unhandled 500 instead of a clean rejection.
    Encoding first keeps the timing-safe guarantee and turns every malformed
    credential into an ordinary mismatch.

    Callers must refuse an empty *expected* secret before calling this:
    an unset secret must fail closed, not match an empty header.
    """
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
