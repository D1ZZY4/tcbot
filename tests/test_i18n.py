# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""i18n engine, locale persistence, and language selection flow."""

from __future__ import annotations

import asyncio
import importlib
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import cfg
from tcbot.database import groups_db, settings_db, users_roles
from tcbot.modules import (
    admins,
    appeals,
    banning,
    broadcasting,
    checking,
    connecting,
    disconnecting,
    groups,
    kicking,
    language,
    maintenance,
    muting,
    netspeed,
    stats,
    syncing,
    unbanning,
    warnings,
)
from tcbot.modules import help as helpmod
from tcbot.modules.helper import keyboards, replies
from tcbot.modules.helper.locale import effective_locale, locale_for_update
from tcbot.modules.helper.workflows.appeal_flow import LOCK_HOURS
from tcbot.utils.formatter import bold, code, esc, pre
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
        self.reads: int = 0

    def _key(self, filt: dict[str, Any]) -> int:
        return int(filt.get("user_id", filt.get("chat_id", 0)))

    async def find_one(
        self, filt: dict[str, Any], proj: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        _ = proj
        self.reads += 1
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
    settings_db._LOCALE_L1.clear()
    return fake


@pytest.fixture()
def fake_group_col(monkeypatch: pytest.MonkeyPatch) -> _FakeCollection:

    fake = _FakeCollection()
    monkeypatch.setattr(groups_db, "col", lambda _name: fake)
    groups_db._GROUP_LOCALE_L1.clear()
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


# ─────── Help rollout: broadcast/connect/groups ─────── #


def test_broadcasting_help_golden() -> None:
    assert broadcasting.__help_text__ == t(
        "broadcasting.help.overview", community=cfg.community_name
    )
    sections = _module_sections(broadcasting)
    assert sections["Commands & Aliases"] == t("broadcasting.help.commands.body")
    assert sections["What it does"] == t(
        "broadcasting.help.what.body", community=cfg.community_name
    )
    assert sections["Examples"] == t("broadcasting.help.examples.body")


def test_connecting_help_golden() -> None:
    assert connecting.__help_text__ == t(
        "connecting.help.overview", community=cfg.community_name
    )
    sections = _module_sections(connecting)
    assert sections["Commands & Aliases"] == t("connecting.help.commands.body")
    assert sections["What it does"] == t(
        "connecting.help.what.body", community=cfg.community_name
    )
    assert sections["Required permissions"] == t("connecting.help.permissions.body")
    assert sections["Notes"] == t("connecting.help.notes.body")
    assert sections["Examples"] == t("connecting.help.examples.body")


def test_disconnecting_help_golden() -> None:
    assert disconnecting.__help_text__ == t(
        "disconnecting.help.overview", community=cfg.community_name
    )
    sections = _module_sections(disconnecting)
    assert sections["Commands & Aliases"] == t("disconnecting.help.commands.body")
    assert sections["What it does"] == t(
        "disconnecting.help.what.body", community=cfg.community_name
    )
    assert sections["Examples"] == t("disconnecting.help.examples.body")


def test_groups_help_golden() -> None:
    assert groups.__help_text__ == t(
        "groups.help.overview", community=cfg.community_name
    )
    sections = _module_sections(groups)
    assert sections["Commands & Aliases"] == t("groups.help.commands.body")
    assert sections["What it does"] == t(
        "groups.help.what.body", community=cfg.community_name
    )
    assert sections["Examples"] == t("groups.help.examples.body")


def test_netspeed_help_golden() -> None:
    assert netspeed.__help_text__ == t("netspeed.help.overview")
    sections = _module_sections(netspeed)
    assert sections["Commands & Aliases"] == t("netspeed.help.commands.body")
    assert sections["What it does"] == t("netspeed.help.what.body")
    assert sections["Examples"] == t("netspeed.help.examples.body")


# ─────── Help rollout: appeals/language/help index ─────── #


def test_appeals_help_golden() -> None:
    window = Safe(bold(f"{LOCK_HOURS}-hour priority window"))
    assert appeals.__help_text__ == t("appeals.help.overview", window=window)
    sections = _module_sections(appeals)
    assert sections["How to start"] == t("appeals.help.start.body")
    assert sections["Who can use"] == replies.who_section(t("appeals.help.who.body"))[1]
    assert sections["Where to start"] == t("appeals.help.where.body")
    assert sections["How it works"] == t("appeals.help.how.body")
    assert sections["Format example"] == pre(t("appeals.help.format.body", plain=True))
    assert sections["What happens next"] == t("appeals.help.next.body", window=window)


def test_language_help_golden() -> None:
    assert language.__help_text__ == t("language.help.overview")
    sections = _module_sections(language)
    assert sections["Commands & Aliases"] == t("language.help.commands.body")
    assert sections["Who can use"] == t("language.help.who.body")
    assert sections["What it does"] == t("language.help.what.body")
    assert sections["Examples"] == t("language.help.examples.body")


def test_help_index_golden() -> None:
    assert helpmod._help_index_text("TestBot") == t(
        "help.index.body",
        title=Safe(bold("TestBot Help")),
        community=cfg.community_name,
    )


def test_user_locale_l1_serves_hits(fake_user_col: _FakeCollection) -> None:
    async def run() -> None:
        await settings_db.set_user_locale(9, "en-US")
        assert fake_user_col.reads == 0
        assert await settings_db.get_user_locale(9) == "en-US"
        assert fake_user_col.reads == 1
        assert await settings_db.get_user_locale(9) == "en-US"
        assert fake_user_col.reads == 1
        await settings_db.set_user_locale(9, None)
        assert await settings_db.get_user_locale(9) is None
        assert fake_user_col.reads == 2

    asyncio.run(run())


def test_group_locale_l1_serves_hits(fake_group_col: _FakeCollection) -> None:
    async def run() -> None:
        fake_group_col.docs[-100] = {"chat_id": -100, "locale": "en-US"}
        assert await groups_db.get_group_locale(-100) == "en-US"
        assert fake_group_col.reads == 1
        assert await groups_db.get_group_locale(-100) == "en-US"
        assert fake_group_col.reads == 1
        await groups_db.set_group_locale(-100, None)
        assert await groups_db.get_group_locale(-100) is None
        assert fake_group_col.reads == 2

    asyncio.run(run())


# ─────── Runtime locale resolution ─────── #


def _pm_update(user_id: int = 7) -> Any:
    return SimpleNamespace(
        effective_chat=SimpleNamespace(type="private", id=user_id),
        effective_user=SimpleNamespace(id=user_id),
    )


def _group_update(chat_id: int = -100, user_id: int = 7) -> Any:
    return SimpleNamespace(
        effective_chat=SimpleNamespace(type="supergroup", id=chat_id),
        effective_user=SimpleNamespace(id=user_id),
    )


def _stub_locales(
    monkeypatch: pytest.MonkeyPatch,
    *,
    user_locale: str | None = None,
    group_locale: str | None = None,
) -> None:
    async def fake_user_locale(_user_id: int) -> str | None:
        return user_locale

    async def fake_group_locale(_chat_id: int) -> str | None:
        return group_locale

    monkeypatch.setattr(settings_db, "get_user_locale", fake_user_locale)
    monkeypatch.setattr(groups_db, "get_group_locale", fake_group_locale)


def test_locale_for_update_pm_uses_user(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_locales(monkeypatch, user_locale="en-US", group_locale="en-US")

    async def run() -> None:
        assert await locale_for_update(_pm_update()) == "en-US"

    asyncio.run(run())


def test_locale_for_update_group_uses_group(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_locales(monkeypatch, user_locale="en-US", group_locale="en-US")

    async def run() -> None:
        assert await locale_for_update(_group_update()) == "en-US"

    asyncio.run(run())


def test_locale_for_update_missing_info_defaults() -> None:
    async def run() -> None:
        empty: Any = SimpleNamespace(effective_chat=None, effective_user=None)
        assert await locale_for_update(empty) == DEFAULT_LOCALE

    asyncio.run(run())


def test_locale_for_update_db_failure_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(_id: int) -> str | None:
        raise RuntimeError("db down")

    monkeypatch.setattr(settings_db, "get_user_locale", boom)
    monkeypatch.setattr(groups_db, "get_group_locale", boom)

    async def run() -> None:
        assert await locale_for_update(_pm_update()) == DEFAULT_LOCALE
        assert await locale_for_update(_group_update()) == DEFAULT_LOCALE

    asyncio.run(run())


# ─────── Runtime goldens: netspeed ─────── #


def test_netspeed_status_plain() -> None:
    assert t("netspeed.status.pinging", DEFAULT_LOCALE, plain=True) == "Pinging..."
    assert (
        t("netspeed.status.running", DEFAULT_LOCALE, plain=True)
        == "Running speed test, please wait..."
    )
    assert (
        t("netspeed.status.timeout", DEFAULT_LOCALE, plain=True)
        == "Speed test timed out. Please try again later."
    )
    assert (
        t("netspeed.status.failed", DEFAULT_LOCALE, plain=True)
        == "Speed test failed. Please try again later."
    )
    assert (
        t("netspeed.status.parse_failed", DEFAULT_LOCALE, plain=True)
        == "Speed test finished but the results could not be read. Please try again later."
    )


def test_netspeed_pong_and_fields_v2_clean() -> None:
    body = t(
        "netspeed.pong.body",
        DEFAULT_LOCALE,
        latency=Safe(code("12.3 ms")),
    )
    assert body == f"Pong\\! Round\\-trip: {code('12.3 ms')}"
    _assert_v2_render_clean(body, "netspeed.pong")
    for key in (
        "ping",
        "timestamp",
        "download",
        "upload",
        "sent",
        "received",
        "ip",
        "isp",
        "isp_rating",
        "country",
        "latitude",
        "longitude",
        "name",
        "sponsor",
        "latency",
    ):
        line = t(f"netspeed.result.field.{key}", DEFAULT_LOCALE, value=Safe(code("x")))
        _assert_v2_render_clean(line, f"netspeed.field.{key}")


# ─────── Shared replies goldens (default locale) ─────── #


def test_replies_errors_golden() -> None:
    pairs = [
        (
            replies.err_cannot_resolve(DEFAULT_LOCALE, plain=True),
            "Cannot resolve that target. Reply to their message, or pass a user ID or @username.",
        ),
        (
            replies.err_role_verify(DEFAULT_LOCALE, plain=True),
            "Could not verify your group role.",
        ),
        (
            replies.err_group_only(DEFAULT_LOCALE, plain=True),
            "Use this command in a group.",
        ),
        (
            replies.err_no_connected_groups(DEFAULT_LOCALE, plain=True),
            "No connected groups.",
        ),
        (
            replies.err_group_not_found(DEFAULT_LOCALE, plain=True),
            "Group not found or already removed.",
        ),
        (
            replies.err_perm_expired(DEFAULT_LOCALE, plain=True),
            "You no longer have permission to do this.",
        ),
        (
            replies.err_unknown_role(DEFAULT_LOCALE, plain=True),
            "Unknown role.",
        ),
        (
            replies.err_groups_load_failed(DEFAULT_LOCALE, plain=True),
            "Could not load the group list. Please try again.",
        ),
    ]
    for got, want in pairs:
        assert got == want
    assert (
        replies.err_group_only(DEFAULT_LOCALE, plain=False)
        == "Use this command in a group\\."
    )
    assert (
        replies.err_groups_load_failed(DEFAULT_LOCALE, plain=False)
        == "Could not load the group list\\. Please try again\\."
    )


def test_replies_tiers_golden() -> None:
    assert replies.perm_founder_only(DEFAULT_LOCALE, plain=False) == "Founder only\\."
    assert (
        replies.perm_staff_only(DEFAULT_LOCALE, plain=False)
        == "TC Staff \\(Admin and above\\)\\."
    )
    assert (
        replies.perm_admin_above(DEFAULT_LOCALE, plain=False)
        == "Admin and above \\(Founder / Admin\\)\\."
    )
    assert (
        replies.perm_dev_above(DEFAULT_LOCALE, plain=False)
        == "Developer and above \\(Founder / Admin / Developer\\)\\."
    )
    assert (
        replies.perm_tester_above(DEFAULT_LOCALE, plain=False)
        == "Tester and above \\(Founder / Admin / Developer / Tester\\)\\."
    )
    assert (
        replies.rate_limit_text(7, DEFAULT_LOCALE, plain=True)
        == "Slow down - try again in 7s."
    )
    assert (
        replies.rate_limit_text(0.2, DEFAULT_LOCALE, plain=True)
        == "Slow down - try again in 1s."
    )
    assert replies.no_reason(DEFAULT_LOCALE, plain=True) == "No reason provided"


# ─────── Per-locale help rendering ─────── #


def test_get_help_matches_default_import() -> None:

    for mod_name in (
        "admins",
        "appeals",
        "banning",
        "broadcasting",
        "checking",
        "connecting",
        "disconnecting",
        "groups",
        "kicking",
        "language",
        "maintenance",
        "muting",
        "netspeed",
        "stats",
        "syncing",
        "unbanning",
        "warnings",
    ):
        mod = importlib.import_module(f"tcbot.modules.{mod_name}")
        assert dict(mod.get_help()) == dict(mod.__help__), mod_name
        assert dict(mod.get_help(DEFAULT_LOCALE)) == dict(mod.__help__), mod_name


def test_builder_help_default_matches_import_content() -> None:
    assert helpmod._builder_help(None) == helpmod.HELP_CONTENT
    assert set(helpmod._builder_help(DEFAULT_LOCALE)) == set(helpmod.HELP_CONTENT)


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
    assert t("banning.help.overview") == (
        "Issues a *federation\\-wide ban* on a user, applied across every "
        "connected group at once\\. Auto\\-demotes staff targets and stores "
        "proof with the ban record\\."
    )


def test_ban_help_commands_golden() -> None:
    assert t("banning.help.commands.body") == "`/tcban` \\(alias: `/tcb`\\)"


def test_ban_help_examples_golden() -> None:
    assert t("banning.help.examples.body") == (
        "`/tcban @username spamming in connected groups`\n"
        "`/tcban 123456789 scamming members`\n"
        "Or reply to a message and run `/tcb reason here`\\."
    )


def test_ban_help_fallback_unknown_locale() -> None:
    assert t("banning.help.overview", "xx-YY") == t("banning.help.overview", "en-US")


def test_ban_help_module_matches_catalog() -> None:
    assert banning.__help_text__ == t("banning.help.overview")
    by_label = dict(banning.__help_sections__)
    assert by_label["Commands & Aliases"] == t("banning.help.commands.body")
    assert by_label["What it does"] == t("banning.help.what.body")
    assert by_label["Flow"] == t("banning.help.flow.body")
    assert by_label["Examples"] == t("banning.help.examples.body")


def test_ban_help_bodies_v2_clean() -> None:
    catalog = _catalog()
    for key in (
        "banning.help.overview",
        "banning.help.commands.body",
        "banning.help.what.body",
        "banning.help.flow.body",
        "banning.help.examples.body",
    ):
        _assert_v2_render_clean(t(key, catalog=catalog), key)


def test_markup_placeholder_inside_span_rejected() -> None:
    catalog = {"en-US": {"m": "Hi {user}, see *{thing}* and `/go`."}}
    with pytest.raises(I18nError):
        t("m", "en-US", catalog=catalog, user="Ann", thing="x")


# ──────────── Help rollout: moderation domains ──────────── #


def _module_sections(mod: Any) -> dict[str, str]:
    return dict(mod.__help_sections__)


def test_kicking_help_golden() -> None:

    assert kicking.__help_text__ == t("kicking.help.overview")
    assert t("kicking.help.overview") == (
        "Removes a user from the *current group only*\\. Auto\\-demotes staff targets\\."
    )
    sections = _module_sections(kicking)
    assert sections["Commands & Aliases"] == t("kicking.help.commands.body")
    assert sections["What it does"] == t("kicking.help.what.body")
    assert sections["Flow"] == t("kicking.help.flow.body")
    assert sections["Examples"] == t("kicking.help.examples.body")


def test_muting_help_golden() -> None:

    assert muting.__help_text__ == t("muting.help.overview")
    sections = _module_sections(muting)
    assert sections["Commands & Aliases"] == t("muting.help.commands.body")
    assert sections["What it does"] == t("muting.help.what.body")
    assert sections["Flow"] == t("muting.help.flow.body")
    assert sections["Time format"] == t("muting.help.time.body")
    assert sections["Examples"] == t("muting.help.examples.body")
    assert t("muting.help.time.body") == (
        "Place the duration before the reason\\. Omit a duration to apply "
        "a permanent mute\\.\n\n"
        "\\- `s` Seconds: `30s` \\= 30 seconds\n"
        "\\- `m` Minutes: `15m` \\= 15 minutes\n"
        "\\- `h` Hours: `2h` \\= 2 hours\n"
        "\\- `d` Days: `7d` \\= 7 days\n"
        "\\- `w` Weeks: `2w` \\= 2 weeks\n"
        "\\- `mo` Months: `3mo` \\= 3 months\n"
        "\\- `ye` Years: `2ye` \\= 2 years"
    )


def test_unbanning_help_golden() -> None:

    assert unbanning.__help_text__ == t("unbanning.help.overview")
    sections = _module_sections(unbanning)
    assert sections["Commands & Aliases"] == t("unbanning.help.commands.body")
    assert sections["What it does"] == t("unbanning.help.what.body")
    assert sections["Examples"] == t("unbanning.help.examples.body")


def test_warnings_help_golden() -> None:
    limit = Safe(bold(f"{cfg.warn_limit} warnings"))
    assert warnings.__help_text__ == t("warnings.help.overview", limit=limit)
    sections = _module_sections(warnings)
    assert sections["Commands & Aliases"] == t("warnings.help.commands.body")
    assert sections["What it does"] == t("warnings.help.what.body", limit=limit)
    assert sections["Flow"] == t("warnings.help.flow.body")
    assert sections["Examples"] == t("warnings.help.examples.body")


# ─────── Help rollout: info and staff domains ─────── #


def test_checking_help_golden() -> None:
    assert checking.__help_text__ == t("checking.help.overview")
    assert t("checking.help.overview") == (
        "Look up your own ban status with `/checkme`, or pull a full "
        "federation activity profile for any user with `/check`\\."
    )
    sections = _module_sections(checking)
    assert sections["Commands & Aliases"] == t("checking.help.commands.body")
    assert sections["/checkme"] == t("checking.help.checkme.body")
    assert sections["/check"] == t("checking.help.check.body")
    assert sections["Examples"] == t("checking.help.examples.body")


def test_stats_help_golden() -> None:
    assert stats.__help_text__ == t("stats.help.overview")
    sections = _module_sections(stats)
    assert sections["Commands & Aliases"] == t("stats.help.commands.body")
    assert sections["What it does"] == t("stats.help.what.body")
    assert sections["Drill-downs"] == t("stats.help.drills.body")
    assert sections["Examples"] == t("stats.help.examples.body")


def test_syncing_help_golden() -> None:
    assert syncing.__help_text__ == t("syncing.help.overview")
    sections = _module_sections(syncing)
    assert sections["Commands & Aliases"] == t("syncing.help.commands.body")
    assert sections["/tcsync"] == t("syncing.help.sync.body")
    assert sections["/tcsync <target>"] == t("syncing.help.sync_target.body")
    assert sections["Examples"] == t("syncing.help.examples.body")


def test_maintenance_help_golden() -> None:
    assert maintenance.__help_text__ == t("maintenance.help.overview")
    sections = _module_sections(maintenance)
    assert sections["Commands & Aliases"] == t("maintenance.help.commands.body")
    assert sections["/leaveall"] == t("maintenance.help.leaveall.body")
    assert sections["/cleanup"] == t("maintenance.help.cleanup.body")
    assert sections["Examples"] == t("maintenance.help.examples.body")


def test_admins_help_golden() -> None:
    assert admins.__help_text__ == t("admins.help.overview")
    assert t("admins.help.overview") == (
        "Promote and demote staff, transfer ownership, and manage "
        "promotion requests across the federation\\."
    )
    sections = _module_sections(admins)
    assert sections["Commands & Aliases"] == t("admins.help.commands.body")
    assert sections["Role Hierarchy"] == t("admins.help.roles.body")
    assert sections["/tcpromote"] == t("admins.help.promote.body")
    assert sections["/tcdemote"] == t("admins.help.demote.body")
    assert sections["/transferowner"] == t("admins.help.transferowner.body")
    assert sections["Examples"] == t("admins.help.examples.body")


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
        assert await effective_locale("private", 1, 10) == "en-US"
        assert await effective_locale("private", 2, 10) == "en-US"
        assert await effective_locale("group", 1, 10) == "en-US"
        assert await effective_locale("group", 1, 99) == "en-US"

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
