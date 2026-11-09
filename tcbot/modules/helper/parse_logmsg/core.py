# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Fluent Markdown audit-log message builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot.utils.formatter import code, esc, link, user_ref
from tcbot.utils.time_and_date import fmt_dt, utc_now

if TYPE_CHECKING:
    from datetime import datetime


class LogBuilder:
    """Fluent builder for Markdown audit-log messages used by the parse_logmsg helpers."""

    __slots__ = ("_lines",)

    def __init__(self, title: str) -> None:
        """Start a new log message with the given title header.

        The title is escaped so callers can pass raw config or user-facing
        strings without risk of breaking the Markdown markup sent to the log channel.
        """
        self._lines: list[str] = [esc(str(title)), ""]

    def field(
        self,
        label: str,
        value: object,
        *,
        escape: bool = True,
    ) -> LogBuilder:
        """Append a `Label: value` line. The value is escaped by default."""
        v = esc(str(value)) if escape else str(value)
        self._lines.append(f"{label}: {v}")
        return self

    def code_field(self, label: str, value: object) -> LogBuilder:
        """Append a `Label: code(value)` line."""
        self._lines.append(f"{label}: {code(str(value))}")
        return self

    def mention_field(
        self, label: str, user_id: int, name: str, username: str | None = None
    ) -> LogBuilder:
        """Append a `Label: user_ref(user_id, name, username)` line."""
        self._lines.append(f"{label}: {user_ref(user_id, name, username)}")
        return self

    def link_field(self, label: str, text: str, url: str) -> LogBuilder:
        """Append a `Label: [text](url)` line."""
        self._lines.append(f"{label}: {link(text, url)}")
        return self

    def raw(self, text: str) -> LogBuilder:
        """Append a raw Markdown line. Caller is responsible for escaping user input."""
        self._lines.append(text)
        return self

    def section(self) -> LogBuilder:
        """Insert a blank separator line between sections."""
        self._lines.append("")
        return self

    def date(self, ts: datetime | None = None, *, label: str = "Date") -> LogBuilder:
        """Append a `Label: dd-mm-yyyy | HH:MM` line. Defaults to utc_now()."""
        self._lines.append(f"{label}: {fmt_dt(ts if ts is not None else utc_now())}")
        return self

    def build(self) -> str:
        """Return the assembled Markdown message."""
        return "\n".join(self._lines)

    def __str__(self) -> str:
        """Delegate to build so str(builder) works naturally."""
        return self.build()
