# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Guard the rich-message transport: no parse modes, no direct rich HTML."""

from __future__ import annotations

import re
from pathlib import Path

_SOURCE = Path(__file__).resolve().parent.parent / "tcbot"

# * A parse mode other than None reintroduces a transport the project removed.
_PARSE_MODE = re.compile(r"""parse_mode\s*=\s*["'](?:HTML|Markdown|MarkdownV2)["']""")

# * style() was the marker for rich HTML handed to a plain PTB call. Rich
# * helpers now build their own payload, so production code has no reason
# * to call the verbatim passthrough.
_STYLE_CALL = re.compile(r"\bstyle\s*\(")


def test_no_parse_mode_outside_none() -> None:
    offenders: list[str] = []
    for path in sorted(_SOURCE.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _PARSE_MODE.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "forbidden parse_mode values: " + ", ".join(offenders)


def test_no_style_passthrough_calls_in_production() -> None:
    offenders: list[str] = []
    for path in sorted(_SOURCE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if path.name == "rich_text.py" and "def style(" in line:
                continue
            if _STYLE_CALL.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "style() passthrough calls: " + ", ".join(offenders)
