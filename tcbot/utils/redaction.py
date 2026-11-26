# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Credential-shape redaction shared by console and report output."""

from __future__ import annotations

import re

# * No leading word boundary: a token inside "bot<token>/..." must still be
# * redacted when the exact configured value is unavailable.
_TOKEN_RE = re.compile(r"(?<!\d)\d{6,}:[A-Za-z0-9_-]{20,}\b")
_URL_CREDENTIALS_RE = re.compile(r"://(?:[^:@/\s]+)?:[^@/\s]+@")


def redact_credential_shapes(text: str) -> str:
    """Mask token-shaped strings and URL credentials in *text*.

    This is the shape-based layer of redaction. Consumers with access to the
    configured values can replace those exactly after calling this helper.
    """
    text = _TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    return _URL_CREDENTIALS_RE.sub("://[REDACTED]@", text)


__all__ = ["redact_credential_shapes"]
