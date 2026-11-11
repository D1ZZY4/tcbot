# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Contract for the callback refusal notice helper.

``cb_error_edit`` is the single owner of the "a tap was refused" shape: it
drops the keyboard so the button cannot be pressed again and it never lets a
failed edit escape into the handler. Its render mode is the part that is easy
to get wrong, because the mode has to match how the notice text was produced.

The text source decides the mode:

- ``t(key, locale, plain=True)`` and ``replies.x(locale, plain=True)`` return
  raw text and must be sent with ``parse_mode=None``.
- everything else (``t(key, locale)``, ``identity.refuse_message``) returns
  MarkdownV2-ready text and must be sent as MarkdownV2.

Sending raw text as MarkdownV2 makes Telegram reject the whole edit, so the
notice never reaches the user. Sending MarkdownV2 as raw text shows the
escape backslashes. Both are silent failures, so the pairing is pinned here.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path

from tcbot.modules.helper.messages.safe_edits import cb_error_edit

_TCBOT_ROOT = Path(__file__).resolve().parent.parent / "tcbot"

# * The keywords the helper accepts. A call site that passes anything else
# * raises TypeError at runtime, which is how a helper signature change can
# * leave the tree green under pytest and still break every refusal.
_ACCEPTED_KEYWORDS = frozenset({"log_label", "parse_mode", "log_level"})


def _call_name(node: ast.Call) -> str:
    """Return the bare name of the callee of ``node``."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _keyword(node: ast.Call, name: str) -> ast.expr | None:
    """Return the value passed for the keyword ``name``, or ``None``."""
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _is_true_literal(node: ast.expr | None) -> bool:
    """Return True when ``node`` is the literal ``True``."""
    return isinstance(node, ast.Constant) and node.value is True


def _cb_error_calls() -> list[tuple[Path, ast.Call]]:
    """Return every ``cb_error_edit`` call site in the package."""
    found: list[tuple[Path, ast.Call]] = []
    for path in sorted(_TCBOT_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found.extend(
            (path, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _call_name(node) == "cb_error_edit"
        )
    return found


def _text_is_plain(text: ast.expr | None) -> bool | None:
    """Return True when the notice text is raw, False for MarkdownV2.

    ``None`` means the source could not be resolved statically, so the call
    site is skipped rather than guessed at.
    """
    if not isinstance(text, ast.Call):
        return None
    name = _call_name(text)
    if name == "t":
        plain = _keyword(text, "plain")
        if plain is None:
            return False
        return _is_true_literal(plain)
    if name == "refuse_message":
        # * The identity refusal is rendered for MarkdownV2 on purpose.
        return False
    if isinstance(text.func, ast.Attribute):
        attr = text.func.attr
        if attr.startswith(("err_", "perm_")):
            plain = _keyword(text, "plain")
            if plain is None:
                return None
            return _is_true_literal(plain)
    return None


def test_cb_error_edit_clears_the_keyboard_and_swallows_failures() -> None:
    """A refusal must drop the keyboard and never fail the handler."""
    calls: list[dict[str, object]] = []

    class _FakeQuery:
        async def edit_message_text(self, text: str, **kwargs: object) -> None:
            calls.append({"text": text, **kwargs})
            raise RuntimeError("telegram is unreachable")

    asyncio.run(cb_error_edit(_FakeQuery(), "nope", log_label="test"))  # type: ignore[arg-type]

    assert len(calls) == 1
    assert calls[0]["reply_markup"] is None
    assert calls[0]["parse_mode"] == "MarkdownV2"


def test_cb_error_edit_default_render_mode_is_markdown() -> None:
    """The default render mode must match the MarkdownV2 notice convention."""
    signature = inspect.signature(cb_error_edit)
    assert signature.parameters["parse_mode"].default == "MarkdownV2"


def test_cb_error_edit_call_sites_only_pass_accepted_keywords() -> None:
    """No call site may pass a keyword the helper does not accept."""
    offenders = [
        f"{path.relative_to(_TCBOT_ROOT)}:{node.lineno} "
        f"passes {sorted({k.arg for k in node.keywords if k.arg} - _ACCEPTED_KEYWORDS)}"
        for path, node in _cb_error_calls()
        if {k.arg for k in node.keywords if k.arg} - _ACCEPTED_KEYWORDS
    ]
    assert not offenders, (
        "cb_error_edit call sites must match the helper:" + "\n  ".join(offenders)
    )


def test_cb_error_edit_call_sites_do_not_manage_the_keyboard() -> None:
    """The helper owns the keyboard, so no call site may pass one."""
    offenders = [
        f"{path.relative_to(_TCBOT_ROOT)}:{node.lineno}"
        for path, node in _cb_error_calls()
        if _keyword(node, "reply_markup") is not None
    ]
    assert not offenders, "cb_error_edit clears the keyboard itself:" + "\n  ".join(
        offenders
    )


def test_cb_error_edit_render_mode_matches_the_notice_text() -> None:
    """The render mode must match how the notice text was produced."""
    offenders: list[str] = []
    for path, node in _cb_error_calls():
        if len(node.args) < 2:
            continue
        plain = _text_is_plain(node.args[1])
        if plain is None:
            continue
        mode = _keyword(node, "parse_mode")
        if mode is None:
            resolved = "MarkdownV2"
        elif isinstance(mode, ast.Constant) and mode.value is None:
            resolved = "plain"
        else:
            resolved = ast.unparse(mode)
        expected = "plain" if plain else "MarkdownV2"
        if resolved != expected:
            offenders.append(
                f"{path.relative_to(_TCBOT_ROOT)}:{node.lineno} "
                f"sends {resolved} text as {expected}"
            )
    assert not offenders, "notice render modes must match the text:" + "\n  ".join(
        offenders
    )


# * The same rule applies to every safe delivery helper, so the check runs
# * over the whole package instead of one helper.
_SAFE_HELPERS = frozenset(
    {"safe_edit", "safe_edit_cb", "safe_edit_message", "safe_reply"}
)


def _safe_calls() -> list[tuple[Path, ast.Call]]:
    """Return every call to one of the safe delivery helpers."""
    found: list[tuple[Path, ast.Call]] = []
    for path in sorted(_TCBOT_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found.extend(
            (path, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _call_name(node) in _SAFE_HELPERS
        )
    return found


def test_every_plain_notice_is_sent_as_plain_text() -> None:
    """Raw notice text must never be sent as MarkdownV2.

    Telegram rejects an unescaped MarkdownV2 message outright, so the edit
    never lands and the user gets no feedback at all. The failure only
    shows up as a warning in the log, which is why the pairing is pinned
    here instead of being left to each call site.
    """
    offenders: list[str] = []
    for path, node in _safe_calls():
        if len(node.args) < 2:
            continue
        if _text_is_plain(node.args[1]) is not True:
            continue
        mode = _keyword(node, "parse_mode")
        if mode is not None and isinstance(mode, ast.Constant) and mode.value is None:
            continue
        offenders.append(
            f"{path.relative_to(_TCBOT_ROOT)}:{node.lineno} "
            f"sends raw text as MarkdownV2"
        )
    assert not offenders, "raw notices must use parse_mode=None:" + "\n  ".join(
        offenders
    )
