# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""i18n engine, locale persistence, and language selection flow."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.database import groups_db, settings_db, users_roles
from tcbot.modules import banning, language
from tcbot.modules.helper import keyboards
from tcbot.utils.formatter import esc
from tcbot.utils.i18n import (
    DEFAULT_LOCALE,
    I18nError,
    Safe,
    available_locales,
    display_name,
    find_unescaped,
    is_known_locale,
    load_catalog,
    placeholders,
    resolve_locale,
    t,
)
from tcbot.utils.prefixes import _PrefixedCommandFilter

ROOT = Path(__file__).resolve().parent.parent / "i18n"


def _catalog() -> dict[str, dict[str, str]]:
    return load_catalog(ROOT)


# ──────────────────────── Catalog loading ───────────────────────── #


def test_default_locale_catalog_loads() -> None:
    catalog = _catalog()
    assert DEFAULT_LOCALE in catalog
    assert "button.back" in catalog[DEFAULT_LOCALE]
    assert "button.language_name" in catalog[DEFAULT_LOCALE]
    assert "language.title_user" in catalog[DEFAULT_LOCALE]


def test_available_locales_sorted() -> None:
    assert available_locales(_catalog()) == sorted(available_locales(_catalog()))
    assert DEFAULT_LOCALE in available_locales(_catalog())


def test_unknown_locale_rejected() -> None:
    assert is_known_locale("xx-YY", _catalog()) is False
    assert is_known_locale("", _catalog()) is False
    assert is_known_locale(None, _catalog()) is False


def test_locale_match_case_insensitive() -> None:
    assert is_known_locale("en-us", _catalog()) is True
    assert display_name("en-us", _catalog()) == display_name("en-US", _catalog())


def test_missing_catalog_root_raises() -> None:
    with pytest.raises(I18nError):
        load_catalog(Path("/nonexistent-i18n-root"))


# ─────────────────────────── Lookup (t) ─────────────────────────── #


def test_t_default_and_explicit() -> None:
    catalog = _catalog()
    assert t("button.cancel", None, catalog=catalog) == t(
        "button.cancel", "en-US", catalog=catalog
    )
    assert t("button.cancel", "xx-YY", catalog=catalog) == t(
        "button.cancel", "en-US", catalog=catalog
    )


def test_t_escapes_string_values() -> None:
    out = t("language.current_user", "en-US", catalog=_catalog(), language="A_B (x).")
    assert out == "Your language: A\\_B \\(x\\)\\.\\."


def test_t_passes_safe_and_numbers_through() -> None:
    catalog = _catalog()
    marked = Safe("[x](tg://user?id=1)")
    out = t("language.current_user", "en-US", catalog=catalog, language=marked)
    assert out == "Your language: [x](tg://user?id=1)\\."
    synthetic = {"en-US": {"n": "Count {n}."}}
    assert t("n", "en-US", catalog=synthetic, n=5) == "Count 5\\."


def test_t_plain_mode_leaves_text_verbatim() -> None:
    catalog = _catalog()
    out = t("language.denied", "en-US", catalog=catalog, plain=True)
    assert "\\" not in out
    assert out == "Only the group owner or staff can change the group language."
    out2 = t(
        "language.current_user", "en-US", catalog=catalog, language="A_B", plain=True
    )
    assert out2 == "Your language: A_B."


def test_t_rejects_specs_and_positional() -> None:
    catalog = {"en-US": {"a": "Hi {x:03d}.", "b": "Hi {x!r}."}}
    with pytest.raises(I18nError):
        t("a", "en-US", catalog=catalog, x=1)
    with pytest.raises(I18nError):
        t("b", "en-US", catalog=catalog, x=1)
    with pytest.raises(I18nError):
        t("button.cancel", "en-US", _catalog(), "extra")


def test_missing_key_returns_marker() -> None:
    assert t("no.such.key", "en-US", catalog=_catalog()) == "[no.such.key]"


def test_t_missing_placeholder_raises() -> None:
    with pytest.raises(I18nError):
        t("language.current_user", "en-US", catalog=_catalog())


def test_t_none_value_raises() -> None:
    with pytest.raises(I18nError):
        t("language.current_user", "en-US", catalog=_catalog(), language=None)


def test_placeholders_extraction() -> None:
    assert placeholders("Hi {user}, {count} left.") == {"user", "count"}
    assert placeholders("No placeholders.") == set()


def test_all_templates_render_v2_clean() -> None:
    catalog = _catalog()
    for locale, keys in catalog.items():
        for key, template in keys.items():
            # * language_name renders on plain buttons and always passes
            # * through placeholder escaping on message paths, so its raw
            # * parens are safe by construction, not by template escaping.
            if key.endswith(".language_name"):
                continue
            dummy: dict[str, Any] = dict.fromkeys(placeholders(template), "x")
            rendered = t(key, locale, catalog=catalog, **dummy)
            _assert_v2_render_clean(rendered, f"{locale}:{key}")


def _strip_code_spans(text: str) -> tuple[str, list[str]]:
    """Remove balanced code spans, returning (remainder, innards)."""
    innards: list[str] = []
    out: list[str] = []

    i, n = 0, len(text)
    while i < n:
        if text[i] == "`":
            j = text.find("`", i + 1)
            assert j > i, "unbalanced code span in rendered output"
            innards.append(text[i + 1 : j])
            out.append("X")
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out), innards


def _assert_v2_render_clean(rendered: str, where: str) -> None:
    """Assert engine output is valid MarkdownV2, markup spans included.

    Code-span innards may only carry doubled backslashes or escaped
    backticks (the engine emits nothing else); bold-span innards and
    the remaining literal text must be fully escaped.
    """
    no_code, code_innards = _strip_code_spans(rendered)
    for inner in code_innards:
        assert "`" not in inner, where
        stripped = re.sub(r"\\\\", "", inner)
        stripped = stripped.replace("\\`", "")
        assert "\\" not in stripped, where
    parts = re.split(r"(?<!\\)\*", no_code)
    assert len(parts) % 2 == 1, f"{where}: unbalanced bold markers"
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            assert find_unescaped(part) == [], f"{where}: bold inner"
        else:
            assert find_unescaped(part) == [], f"{where}: literal"


def test_non_default_locales_subset_default_keys() -> None:
    catalog = _catalog()
    default_keys = set(catalog[DEFAULT_LOCALE])
    for locale, keys in catalog.items():
        if locale == DEFAULT_LOCALE:
            continue
        assert set(keys) <= default_keys, locale


# ─────────────────────── Locale resolution ──────────────────────── #


def test_resolve_private_prefers_user() -> None:
    assert (
        resolve_locale(chat_type="private", user_locale="en-US", group_locale=None)
        == "en-US"
    )
    assert (
        resolve_locale(chat_type="private", user_locale=None, group_locale="en-US")
        == "en-US"
    )


def test_resolve_group_prefers_group() -> None:
    assert (
        resolve_locale(chat_type="group", user_locale="en-US", group_locale="en-US")
        == "en-US"
    )
    assert (
        resolve_locale(chat_type="supergroup", user_locale="en-US", group_locale=None)
        == "en-US"
    )


def test_resolve_explicit_wins_everywhere() -> None:
    assert (
        resolve_locale(
            chat_type="group",
            user_locale="en-US",
            group_locale="en-US",
            explicit="en-US",
        )
        == "en-US"
    )


def test_resolve_unknown_falls_back() -> None:
    assert resolve_locale(chat_type="private", user_locale="xx-YY") == DEFAULT_LOCALE
    assert resolve_locale(chat_type="group", group_locale="xx-YY") == DEFAULT_LOCALE
    assert (
        resolve_locale(chat_type="group", group_locale="en-US", explicit="xx-YY")
        == "en-US"
    )


# ─────────────────── Persistence fakes and tests ─────────────────── #


class _FakeResult:
    def __init__(self, matched_count: int = 0) -> None:
        self.matched_count = matched_count


class _FakeCollection:
    """Minimal async stand-in for the Motor calls locale helpers use."""

    def __init__(self) -> None:
        self.docs: dict[int, dict[str, Any]] = {}

    def _key(self, filt: dict[str, Any]) -> int:
        return int(filt.get("user_id", filt.get("chat_id", 0)))

    async def find_one(
        self, filt: dict[str, Any], proj: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        _ = proj
        doc = self.docs.get(self._key(filt))
        return dict(doc) if doc is not None else None

    async def update_one(
        self,
        filt: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> _FakeResult:
        key = self._key(filt)
        doc = self.docs.get(key)
        if doc is None:
            if not upsert:
                return _FakeResult(0)
            doc = dict(filt)
            self.docs[key] = doc
        for field, value in update.get("$set", {}).items():
            doc[field] = value
        for field in update.get("$unset", {}):
            doc.pop(field, None)
        return _FakeResult(1)

    async def delete_one(self, filt: dict[str, Any]) -> _FakeResult:
        return _FakeResult(1 if self.docs.pop(self._key(filt), None) is not None else 0)


@pytest.fixture()
def fake_user_col(monkeypatch: pytest.MonkeyPatch) -> _FakeCollection:

    fake = _FakeCollection()
    monkeypatch.setattr(settings_db, "col", lambda _name: fake)
    return fake


@pytest.fixture()
def fake_group_col(monkeypatch: pytest.MonkeyPatch) -> _FakeCollection:

    fake = _FakeCollection()
    monkeypatch.setattr(groups_db, "col", lambda _name: fake)
    return fake


def test_user_locale_roundtrip(fake_user_col: _FakeCollection) -> None:

    async def run() -> None:
        assert await settings_db.get_user_locale(1) is None
        await settings_db.set_user_locale(1, "en-US")
        assert await settings_db.get_user_locale(1) == "en-US"
        await settings_db.set_user_locale(1, None)
        assert await settings_db.get_user_locale(1) is None
        assert 1 not in fake_user_col.docs

    asyncio.run(run())


def test_user_locales_isolated(fake_user_col: _FakeCollection) -> None:

    async def run() -> None:
        await settings_db.set_user_locale(1, "en-US")
        await settings_db.set_user_locale(2, "en-US")
        await settings_db.set_user_locale(1, None)
        assert await settings_db.get_user_locale(1) is None
        assert await settings_db.get_user_locale(2) == "en-US"

    asyncio.run(run())


def test_group_locale_roundtrip(fake_group_col: _FakeCollection) -> None:

    async def run() -> None:
        fake_group_col.docs[10] = {"chat_id": 10}
        assert await groups_db.get_group_locale(10) is None
        assert await groups_db.set_group_locale(10, "en-US") is True
        assert await groups_db.get_group_locale(10) == "en-US"
        assert await groups_db.set_group_locale(10, None) is True
        assert await groups_db.get_group_locale(10) is None

    asyncio.run(run())


def test_group_locale_missing_group(fake_group_col: _FakeCollection) -> None:

    async def run() -> None:
        assert await groups_db.get_group_locale(999) is None
        assert await groups_db.set_group_locale(999, "en-US") is False

    asyncio.run(run())


# ─────────────────── Module wiring and callbacks ────────────────── #


def _message(text: str) -> Any:
    return SimpleNamespace(
        text=text, get_bot=lambda: SimpleNamespace(username="Bot"), chat_id=1
    )


def test_command_aliases_match() -> None:

    for alias in ("language", "lang", "langs"):
        filt = _PrefixedCommandFilter(alias, ["/", "!", "."])
        assert filt.filter(_message(f"/{alias}")) is True
    filt = _PrefixedCommandFilter("lang", ["/"])
    assert filt.filter(_message("/language")) is False
    assert filt.filter(_message("/languag")) is False


def test_module_handlers_registered() -> None:
    kinds = {type(h).__name__ for h in language.__handlers__}
    assert "MessageHandler" in kinds
    assert "CallbackQueryHandler" in kinds
    assert language.__module_name__ == "Language"
    assert language.__help__["name"] == "Language"


def test_callback_patterns() -> None:
    assert re.fullmatch(language._LIST_PATTERN, "lang:list:user") is not None
    assert re.fullmatch(language._LIST_PATTERN, "lang:list:group") is not None
    assert re.fullmatch(language._SET_PATTERN, "lang:set:user:en-US") is not None
    assert re.fullmatch(language._SET_PATTERN, "lang:set:group:en-US") is not None
    # * Shape-valid but unknown codes pass the regex; the handler rejects
    # * them via is_known_locale with the unavailable reply.
    assert re.fullmatch(language._SET_PATTERN, "lang:set:user:xx") is not None
    assert re.fullmatch(language._SET_PATTERN, "lang:set:admin:en-US") is None


def test_chat_scope() -> None:
    assert language._chat_scope("private") == "user"
    assert language._chat_scope("group") == "group"
    assert language._chat_scope("supergroup") == "group"
    assert language._chat_scope(None) == "group"


def test_start_menu_has_language_bottom_row() -> None:
    kb = keyboards.main_menu_kb()
    rows = kb.inline_keyboard
    assert rows
    bottom = rows[-1]
    assert len(bottom) == 1
    assert bottom[0].text == "Language"
    assert bottom[0].callback_data == "language_menu"


def test_language_list_marks_selected_locale() -> None:
    kb = keyboards.language_list_kb(
        "user",
        [("English (US)", "en-US"), ("Bahasa Indonesia", "id")],
        selected="en-US",
    )
    texts = [row[0].text for row in kb.inline_keyboard]
    assert texts[0] == "✓ English (US)"
    assert texts[1] == "Bahasa Indonesia"
    assert kb.inline_keyboard[0][0].callback_data == "lang:set:user:en-US"


def test_panel_renders_v2_clean() -> None:
    for scope in ("user", "group"):
        text = language._panel_text(scope, "en-US")
        assert find_unescaped(text) == []
        assert "en-US" not in text
    confirm = language._confirmation_text("user", "en-US")
    assert find_unescaped(confirm) == []


def test_esc_import_used_by_engine() -> None:
    assert esc("a_b") == "a\\_b"


# ─────────────────────── Mini-markup ──────────────────────── #


def test_markup_code_and_bold() -> None:
    catalog = {"en-US": {"m": "Run `/tcban` then tap *Done*."}}
    out = t("m", "en-US", catalog=catalog)
    assert out == "Run `/tcban` then tap *Done*\\."


def test_markup_code_span() -> None:
    catalog = {"en-US": {"m": "Tap `/tcb reason here`."}}
    assert t("m", "en-US", catalog=catalog) == "Tap `/tcb reason here`\\."


def test_markup_bold_span() -> None:
    catalog = {"en-US": {"m": "A *federation-wide ban* on the target."}}
    assert (
        t("m", "en-US", catalog=catalog) == "A *federation\\-wide ban* on the target\\."
    )


def test_markup_plain_mode_strips_markers() -> None:
    catalog = {"en-US": {"m": "Tap *Done* or `/skip` now."}}
    assert t("m", "en-US", catalog=catalog, plain=True) == "Tap Done or /skip now."


def test_markup_unbalanced_rejected() -> None:
    for bad in ("Tap `code now.", "Tap *bold now.", "Tap code` now.", "Tap bold* now."):
        with pytest.raises(I18nError):
            t("m", "en-US", catalog={"en-US": {"m": bad}})


def test_markup_empty_span_rejected() -> None:
    for bad in ("Tap `` now.", "Tap ** now."):
        with pytest.raises(I18nError):
            t("m", "en-US", catalog={"en-US": {"m": bad}})


def test_markup_nesting_rejected() -> None:
    with pytest.raises(I18nError):
        t("m", "en-US", catalog={"en-US": {"m": "*a `b` c*"}}, b="x")
    with pytest.raises(I18nError):
        t("m", "en-US", catalog={"en-US": {"m": "`a {b}`"}}, b="x")


def test_markup_sequential_pairs_parse() -> None:
    # * First-close-wins pairing (standard Markdown interpretation):
    # * bold, literal, bold. Telegram parses the same shape.
    catalog = {"en-US": {"m": "*a *b* c*"}}
    assert t("m", "en-US", catalog=catalog) == "*a *b* c*"


def test_markup_brace_in_span_rejected() -> None:
    with pytest.raises(I18nError):
        t("m", "en-US", catalog={"en-US": {"m": "`/x {y}`"}}, y="z")


def test_markup_placeholder_beside_spans() -> None:
    catalog = {"en-US": {"m": "Banned {user} - see *details* in `/log`."}}
    out = t("m", "en-US", catalog=catalog, user="A_B")
    assert out == "Banned A\\_B \\- see *details* in `/log`\\."


def test_markup_stray_brace_rejected() -> None:
    with pytest.raises(I18nError):
        t("m", "en-US", catalog={"en-US": {"m": "Hi } there."}})
    with pytest.raises(I18nError):
        t("m", "en-US", catalog={"en-US": {"m": "Hi { there."}})


def test_markup_escaped_braces_literal() -> None:
    catalog = {"en-US": {"m": "Use {{x}} literally."}}
    assert t("m", "en-US", catalog=catalog) == "Use \\{x\\} literally\\."


# ─────────────────── Ban help pilot (Opsi B) ─────────────────── #


def test_ban_help_overview_golden() -> None:
    assert t("ban.help.overview") == (
        "Issues a *federation\\-wide ban* on a user, applied across every "
        "connected group at once\\. Auto\\-demotes staff targets and stores "
        "proof with the ban record\\."
    )


def test_ban_help_commands_golden() -> None:
    assert t("ban.help.commands.body") == "`/tcban` \\(alias: `/tcb`\\)"


def test_ban_help_examples_golden() -> None:
    assert t("ban.help.examples.body") == (
        "`/tcban @username spamming in connected groups`\n"
        "`/tcban 123456789 scamming members`\n"
        "Or reply to a message and run `/tcb reason here`\\."
    )


def test_ban_help_fallback_unknown_locale() -> None:
    assert t("ban.help.overview", "xx-YY") == t("ban.help.overview", "en-US")


def test_ban_help_module_matches_catalog() -> None:
    assert banning.__help_text__ == t("ban.help.overview")
    by_label = dict(banning.__help_sections__)
    assert by_label["Commands & Aliases"] == t("ban.help.commands.body")
    assert by_label["What it does"] == t("ban.help.what.body")
    assert by_label["Flow"] == t("ban.help.flow.body")
    assert by_label["Examples"] == t("ban.help.examples.body")


def test_ban_help_bodies_v2_clean() -> None:
    catalog = _catalog()
    for key in (
        "ban.help.overview",
        "ban.help.commands.body",
        "ban.help.what.body",
        "ban.help.flow.body",
        "ban.help.examples.body",
    ):
        _assert_v2_render_clean(t(key, catalog=catalog), key)


def test_markup_placeholder_inside_span_rejected() -> None:
    catalog = {"en-US": {"m": "Hi {user}, see *{thing}* and `/go`."}}
    with pytest.raises(I18nError):
        t("m", "en-US", catalog=catalog, user="Ann", thing="x")


# ─────────────── Handler flows with fakes ─────────────────── #


class _FakeMessage:
    def __init__(self, chat_type: str = "private") -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.chat_id = 10
        self.chat_type = chat_type

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        self.sent.append((text, kwargs))


class _FakeQuery:
    def __init__(self, data: str | None) -> None:
        self.data = data
        self.answers: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.edits: list[tuple[str, dict[str, Any]]] = []
        self.message = SimpleNamespace(text="panel")

    async def answer(self, *args: Any, **kwargs: Any) -> None:
        self.answers.append((args, kwargs))

    async def edit_message_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append((text, kwargs))


class _FakeBot:
    def __init__(self, status: str = "creator") -> None:
        self._status = status

    async def get_chat_member(self, chat_id: int, user_id: int) -> Any:
        _ = (chat_id, user_id)
        return SimpleNamespace(status=self._status)


def _update(
    *,
    chat_type: str = "private",
    user_id: int = 1,
    query: _FakeQuery | None = None,
    msg: _FakeMessage | None = None,
) -> tuple[Any, _FakeMessage]:
    message = msg if msg is not None else _FakeMessage(chat_type)
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=user_id, first_name="Ann"),
        effective_chat=SimpleNamespace(id=10, type=chat_type),
        callback_query=query,
    )
    return update, message


def test_effective_locale_pm_and_group(monkeypatch: pytest.MonkeyPatch) -> None:

    async def fake_user(uid: int) -> str | None:
        return "en-US" if uid == 1 else None

    async def fake_group(cid: int) -> str | None:
        return "en-US" if cid == 10 else None

    monkeypatch.setattr(settings_db, "get_user_locale", fake_user)
    monkeypatch.setattr(groups_db, "get_group_locale", fake_group)

    async def run() -> None:
        assert await language._effective_locale("private", 1, 10) == "en-US"
        assert await language._effective_locale("private", 2, 10) == "en-US"
        assert await language._effective_locale("group", 1, 10) == "en-US"
        assert await language._effective_locale("group", 1, 99) == "en-US"

    asyncio.run(run())


def test_can_set_group_matrix(monkeypatch: pytest.MonkeyPatch) -> None:

    async def _staff_true(uid: int) -> bool:
        return True

    async def _staff_false(uid: int) -> bool:
        return False

    async def run() -> None:
        monkeypatch.setattr(users_roles, "is_staff", _staff_true)
        assert await language._can_set_group(_FakeBot("member"), 10, 7) is True
        monkeypatch.setattr(users_roles, "is_staff", _staff_false)
        assert await language._can_set_group(_FakeBot("creator"), 10, 7) is True
        assert await language._can_set_group(_FakeBot("member"), 10, 7) is False
        assert await language._can_set_group(_FakeBot("left"), 10, 7) is False

    asyncio.run(run())


def test_cmd_language_pm_panel(monkeypatch: pytest.MonkeyPatch) -> None:

    async def _owner() -> int:
        return 999

    async def _no_user(uid: int) -> str | None:
        return None

    async def _no_group(cid: int) -> str | None:
        return None

    monkeypatch.setattr(users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(settings_db, "get_user_locale", _no_user)
    monkeypatch.setattr(groups_db, "get_group_locale", _no_group)

    async def run() -> None:
        update, message = _update(chat_type="private")
        await language.cmd_language(update, SimpleNamespace(user_data={}))
        assert len(message.sent) == 1
        text, kwargs = message.sent[0]
        assert kwargs.get("parse_mode", "MarkdownV2") == "MarkdownV2"
        assert find_unescaped(text) == []
        assert kwargs["reply_markup"] is not None

    asyncio.run(run())


def test_on_lang_set_user_saves(
    monkeypatch: pytest.MonkeyPatch, fake_user_col: _FakeCollection
) -> None:

    async def _owner() -> int:
        return 999

    monkeypatch.setattr(users_roles, "get_owner_id", _owner)

    async def run() -> None:
        query = _FakeQuery("lang:set:user:en-US")
        update, _ = _update(chat_type="private", query=query)
        await language.on_lang_set(update, SimpleNamespace())
        assert query.answers
        assert len(query.edits) == 1
        text, kwargs = query.edits[0]
        assert kwargs.get("parse_mode") == "MarkdownV2"
        assert find_unescaped(text) == []
        assert await settings_db.get_user_locale(1) == "en-US"

    monkeypatch.setattr(settings_db, "col", lambda _name: fake_user_col)
    asyncio.run(run())


def test_on_lang_set_group_denied(monkeypatch: pytest.MonkeyPatch) -> None:

    async def _owner() -> int:
        return 999

    async def _staff_false(uid: int) -> bool:
        return False

    monkeypatch.setattr(users_roles, "get_owner_id", _owner)

    async def run() -> None:
        monkeypatch.setattr(users_roles, "is_staff", _staff_false)
        query = _FakeQuery("lang:set:group:en-US")
        update, _ = _update(chat_type="group", query=query)
        await language.on_lang_set(update, SimpleNamespace(bot=_FakeBot("member")))
        assert query.answers
        assert query.edits == []

    asyncio.run(run())
