# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Guard the rich-message transport: no parse modes, no direct rich HTML."""

from __future__ import annotations

import ast
import re
from pathlib import Path

_SOURCE = Path(__file__).resolve().parent.parent / "tcbot"

# * A parse mode other than None reintroduces a transport the project removed.
_PARSE_MODE = re.compile(r"""parse_mode\s*=\s*["'](?:HTML|Markdown|MarkdownV2)["']""")

# * Rich helpers build their own payload, so production code has no reason
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
            if path.name == "text.py" and "def style(" in line:
                continue
            if _STYLE_CALL.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "style() passthrough calls: " + ", ".join(offenders)


# * Every message a user sees must travel through rich/send_msg.py,
# * rich/reply_msg.py, or rich/edit_msg.py. A module that reaches into a
# * low-level send silently abandons rich buttons and rich blocks.
_RAW_TRANSPORT = re.compile(
    r"\.(?:send_message|reply_text|edit_text|edit_message_text|edit_message_caption|"
    r"send_photo|send_video|send_document|send_animation|send_media_group|"
    r"send_voice|send_audio|send_sticker|forward)\s*\("
)
_TRANSPORT_OWNERS = frozenset({"send_msg.py", "edit_msg.py", "forward_msg.py"})


def test_no_raw_message_transport_calls_outside_rich_owners() -> None:
    offenders: list[str] = []
    for path in sorted(_SOURCE.rglob("*.py")):
        if path.name in _TRANSPORT_OWNERS and path.parent.name == "rich":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _RAW_TRANSPORT.search(line):
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert not offenders, "raw message transports: " + ", ".join(offenders)


# * The string rule above misses aliased calls and canonical rich method names.
# * Resolve the callee of every call in the AST instead, including getattr with
# * a constant method name.
_DELIVERY_METHODS = frozenset(
    {
        "send_message",
        "send_rich_message",
        "reply_text",
        "reply_rich",
        "edit_text",
        "edit_message_text",
        "edit_message_reply_markup",
        "edit_message_caption",
        "edit_message_media",
        "send_photo",
        "send_video",
        "send_document",
        "send_animation",
        "send_voice",
        "send_audio",
        "send_sticker",
        "send_poll",
        "send_location",
        "send_media_group",
        "forward",
    }
)
_RICH_OWNERS = frozenset(
    {"send_msg.py", "reply_msg.py", "edit_msg.py", "forward_msg.py"}
)


def _called_method(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if (
        isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    ):
        return node.args[1].value
    return None


def test_only_rich_owner_modules_call_delivery_methods() -> None:
    offenders: list[str] = []
    for path in sorted(_SOURCE.rglob("*.py")):
        if path.parent.name == "rich" and path.name in _RICH_OWNERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            method = _called_method(node)
            if method in _DELIVERY_METHODS:
                offenders.append(f"{path}:{node.lineno}: {method}")
    assert not offenders, "delivery calls outside rich owners: " + ", ".join(offenders)
