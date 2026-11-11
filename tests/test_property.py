# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Property-based checks for formatter escaping, list parsing, and links."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from tcbot import parse_list
from tcbot.modules.helper.messages import chat_id_to_link_id, message_link
from tcbot.utils.formatter import _MD_V2_TEXT_SPECIAL, esc

# * Keep examples fast: the suite already covers behaviour with unit tests,
# * these invariants are ordering/shape checks only.
MAX_EXAMPLES = 50

_SPECIAL_ALPHABET = "abcXYZ019 _*[]()~`>#+-=|{}.!\\"


def _is_fully_escaped(text: str) -> bool:
    """Walk output pairwise: every special char must sit behind a backslash."""
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] in _MD_V2_TEXT_SPECIAL:
            return False
        i += 1
    return True


@given(st.text(alphabet=_SPECIAL_ALPHABET, max_size=40))
@settings(max_examples=MAX_EXAMPLES)
def test_esc_escapes_every_special(text: str) -> None:
    """esc() output must leave no unescaped MarkdownV2 special character."""
    assert _is_fully_escaped(esc(text))


@given(st.text(max_size=60))
@settings(max_examples=MAX_EXAMPLES)
def test_parse_list_never_raises(text: str) -> None:
    """parse_list returns a list of strings for any input shape."""
    result = parse_list(text)
    assert isinstance(result, list)
    assert all(isinstance(item, str) for item in result)


@given(
    st.integers(min_value=-(10**12), max_value=10**12),
    st.integers(min_value=1, max_value=10**9),
)
@settings(max_examples=MAX_EXAMPLES)
def test_message_link_roundtrip_style(chat_id: int, message_id: int) -> None:
    """message_link strips one -100 prefix and formats the canonical URL."""
    link = message_link(chat_id, message_id)
    assert link == f"https://t.me/c/{chat_id_to_link_id(chat_id)}/{message_id}"
    assert message_id != 0
    # * Supergroup ids keep working through the strip rule only when they
    # * were -100-prefixed; other negatives lose only the minus sign.
    assert chat_id_to_link_id(chat_id) == (
        str(chat_id)[4:]
        if str(chat_id).startswith("-100")
        else str(chat_id).lstrip("-")
    )
