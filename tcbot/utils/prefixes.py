# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Build command filters that match all configured prefixes (/, !, .)."""
from __future__ import annotations

import ast
import os
import re

from telegram.ext import filters


def _get_prefixes() -> list[str]:
    """Parse PREFIXES env var – handles both list format and plain string."""
    raw = os.getenv("PREFIXES", "").strip()
    if not raw:
        return ["/", "!", "."]

    ## Try Python list literal: ["/", "!", "."]
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return [str(p) for p in parsed if p]
    except Exception:
        pass

    ## Fall back to treating each character as a prefix
    return list(raw)


def build_prefixed_filters(command: str) -> filters.BaseFilter:
    """Return a filter matching <prefix><command> for all configured prefixes."""
    prefixes = _get_prefixes()
    escaped_prefixes = re.escape("".join(set(prefixes)))
    pattern = rf"^[{escaped_prefixes}]{re.escape(command)}(?:@\w+)?(?:\s|$)"
    return filters.Regex(re.compile(pattern, re.IGNORECASE))


def parse_cmd_args(text: str | None) -> list[str]:
    """Extract arguments from a prefixed command message text."""
    if not text:
        return []
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        return []
    return parts[1].split()
