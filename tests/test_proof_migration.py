# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Tests for scripts/migrate_proofs.py pure helpers."""

from __future__ import annotations

import importlib.util
import json
import pathlib
from types import SimpleNamespace

_SCRIPT = (
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "migrate_proofs.py"
)
_spec = importlib.util.spec_from_file_location("migrate_proofs", _SCRIPT)
assert _spec is not None and _spec.loader is not None
mp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mp)


class _Btn:
    """Fake pyrogram button (attribute access only)."""

    def __init__(
        self, text: str, url: str | None = None, callback_data: str | None = None
    ):
        self.text = text
        self.url = url
        self.callback_data = callback_data


def _markup(*rows: list[_Btn]) -> SimpleNamespace:
    return SimpleNamespace(inline_keyboard=list(rows))


OLD = -1003999999999
NEW = -1003997518221
OLD_LINK = mp.proof_link(OLD, 12)
NEW_LINK = mp.proof_link(NEW, 555)


def test_chat_link_id() -> None:
    assert mp.chat_link_id(-1003997518221) == "3997518221"
    assert mp.chat_link_id(-12345) == "12345"
    assert mp.chat_link_id(12345) == "12345"


def test_proof_link() -> None:
    assert mp.proof_link(NEW, 555) == "https://t.me/c/3997518221/555"


def test_url_matches_bare_and_thread() -> None:
    assert mp.url_matches(OLD_LINK, OLD_LINK)
    assert mp.url_matches(OLD_LINK + "?thread=7", OLD_LINK)
    assert not mp.url_matches(mp.proof_link(OLD, 99), OLD_LINK)
    assert not mp.url_matches(NEW_LINK, OLD_LINK)


def test_swap_link_url() -> None:
    links = {OLD_LINK: NEW_LINK}
    assert mp.swap_link_url(OLD_LINK, links) == NEW_LINK
    assert mp.swap_link_url(OLD_LINK + "?thread=3", links) == NEW_LINK
    untouched = "https://t.me/bot?start=appeal_x1"
    assert mp.swap_link_url(untouched, links) == untouched


def test_build_link_map() -> None:
    assert mp.build_link_map(OLD, NEW, 12, 555) == {OLD_LINK: NEW_LINK}
    assert mp.build_link_map(OLD, NEW, 0, 555) == {}
    assert mp.build_link_map(OLD, NEW, None, 555) == {}
    assert mp.build_link_map(OLD, NEW, 12, None) == {}


def test_state_roundtrip(tmp_path) -> None:
    path = str(tmp_path / "state.json")
    state = {"done": {"b1": {"proof_new": 555}}, "copies": {"12": 555}}
    mp.save_state(path, state)
    assert mp.load_state(path) == state
    assert json.loads(pathlib.Path(path).read_text(encoding="utf-8")) == state


def test_state_missing_and_bad(tmp_path) -> None:
    missing = str(tmp_path / "nope.json")
    assert mp.load_state(missing) == {"done": {}, "copies": {}}
    bad = tmp_path / "bad.json"
    bad.write_text("not-json{", encoding="utf-8")
    assert mp.load_state(str(bad)) == {"done": {}, "copies": {}}


def test_ban_ids_pending_skips_done() -> None:
    bans = [{"ban_id": "a"}, {"ban_id": "b"}, {"ban_id": "c"}]
    state = {"done": {"b": {"done": True}}, "copies": {}}
    assert mp.ban_ids_pending(bans, state) == ["a", "c"]


def test_rebuild_markup_swaps_urls() -> None:
    markup = _markup(
        [_Btn("Proof (1)", url=OLD_LINK)],
        [_Btn("Prev", url=OLD_LINK + "?thread=5"), _Btn("Go", callback_data="x")],
    )
    new_markup, changed = mp.rebuild_markup(markup, {OLD_LINK: NEW_LINK})
    assert changed == 2
    assert new_markup is not None
    rows = new_markup.inline_keyboard
    assert rows[0][0].url == NEW_LINK
    assert rows[1][0].url == NEW_LINK
    assert rows[1][1].callback_data == "x"


def test_rebuild_markup_untouched_when_no_match() -> None:
    markup = _markup([_Btn("Appeal", url="https://t.me/bot?start=appeal_x1")])
    new_markup, changed = mp.rebuild_markup(markup, {OLD_LINK: NEW_LINK})
    assert changed == 0
    assert new_markup is not None
    assert new_markup.inline_keyboard[0][0].url == "https://t.me/bot?start=appeal_x1"


def test_rebuild_markup_unknown_buttons_abort_edit() -> None:
    markup = _markup([_Btn("Proof", url=OLD_LINK), _Btn("Odd")])
    new_markup, changed = mp.rebuild_markup(markup, {OLD_LINK: NEW_LINK})
    assert changed == 1
    assert new_markup is None


def test_is_flood() -> None:
    assert mp._is_flood(type("FloodWait", (), {"value": 5})())
    assert mp._is_flood(type("RetryAfter", (), {"retry_after": 5})())
    assert mp._is_flood(ValueError("flood wait of 5 seconds"))
    assert not mp._is_flood(ValueError("Nope"))


def test_parse_args_defaults() -> None:
    args = mp.parse_args(["--old-proof-chat", "-1001", "--logs-chat", "-1002"])
    assert args.new_proof_chat == mp.DEFAULT_NEW_PROOF_CHAT
    assert args.apply is False
    args = mp.parse_args(
        ["--old-proof-chat", "-1001", "--logs-chat", "-1002", "--apply"]
    )
    assert args.apply is True
