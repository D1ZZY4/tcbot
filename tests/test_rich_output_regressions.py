# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Regressions for help tables, speed-test tables, and summary punctuation."""

from __future__ import annotations

from typing import Any

import pytest

from tcbot.modules.helper.messages import rich_text
from tcbot.modules.helper.messages.replies import applied_summary
from tcbot.modules.netspeed import _render_result
from tcbot.utils.i18n import t

_EXAMPLE_LOCALES = ("en-US", "id-ID")
_EXAMPLE_MODULES = (
    "admins",
    "disconnecting",
    "kicking",
    "maintenance",
    "muting",
    "warnings",
)


@pytest.mark.parametrize("locale", _EXAMPLE_LOCALES)
@pytest.mark.parametrize("module", _EXAMPLE_MODULES)
def test_help_examples_have_no_orphan_colon(module: str, locale: str) -> None:
    """A colon after a command code span becomes its own Details cell."""
    rendered = rich_text.blocks(t(f"{module}.help.examples.body", locale))
    assert "`: " not in rendered
    assert "<td>: " not in rendered


@pytest.mark.parametrize("locale", _EXAMPLE_LOCALES)
def test_appeal_format_example_keeps_its_preformatted_block(locale: str) -> None:
    """blocks() must not split a <pre><code> example into paragraphs."""
    body = t("appeals.help.format.body", locale, plain=True)
    rendered = rich_text.blocks(f"<pre><code>{body}</code></pre>")
    assert "<pre><code>" in rendered
    assert rendered.count("<p>") == 0


@pytest.mark.parametrize("locale", _EXAMPLE_LOCALES)
def test_speedtest_result_is_three_tables(locale: str) -> None:
    """The result, client, and server groups each render as a rich table."""
    result: dict[str, Any] = {
        "ping": 12.3,
        "timestamp": "1795352220",
        "download": 1_000_000.0,
        "upload": 500_000.0,
        "bytes_sent": 262_144,
        "bytes_received": 1_048_576,
        "client": {
            "ip": "203.0.113.5",
            "isp": "Example",
            "isprating": "3.7",
            "country": "US",
            "lat": "33.4",
            "lon": "-112.0",
        },
        "server": {
            "name": "Seoul",
            "sponsor": "kdatacenter.com",
            "latency": 12.3,
            "country": "South Korea",
            "cc": "KR",
            "lat": "37.5",
            "lon": "127.0",
        },
    }
    text = _render_result(
        result,
        download="1.00 MB",
        upload="500.00 KB",
        sent="256.00 KB",
        received="1.00 MB",
        locale=locale,
    )
    assert text.count("<table") == 3
    assert text.count("<hr/>") == 3
    assert "<h2>" in text
    assert "<h3>" in text
    assert "Label: value" not in text


@pytest.mark.parametrize("locale", _EXAMPLE_LOCALES)
def test_partial_summary_has_one_closing_parenthesis(locale: str) -> None:
    """The template already carries the closing bracket after {more}."""
    line = applied_summary(
        locale,
        "banning.applied",
        total=3,
        failed=1,
        pending=0,
        transient=[({"title": "Alpha", "chat_id": -1}, RuntimeError("x"))],
    )
    assert "))" not in line
    assert line.count("(") == line.count(")")
