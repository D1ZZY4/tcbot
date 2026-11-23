# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""About and connect-verification copy matches the shipped moderation scope."""

from __future__ import annotations

import tomllib
from pathlib import Path

from tcbot.modules.helper.buttons.flows import connect_verify_btn
from tcbot.modules.helper.messages import panels
from tcbot.modules.helper.pipelines import connect_verify
from tcbot.modules.helper.pipelines.connect_added import BuildConnection

_ROOT = Path(__file__).resolve().parents[1]
_LOCALES = ("en-US", "id-ID")


def _catalog(locale: str, name: str) -> dict[str, object]:
    path = _ROOT / "i18n" / locale / f"{name}.toml"
    with path.open("rb") as fh:
        return tomllib.load(fh)


def test_about_item_counts_match_both_catalogs() -> None:
    """Every rendered About item has wording in both locales, and no orphan."""
    for locale in _LOCALES:
        sections = _catalog(locale, "about")["section"]
        assert isinstance(sections, dict)
        for key, count in panels._ABOUT_ITEM_COUNTS.items():
            section = sections[key]
            assert isinstance(section, dict)
            assert f"item_{count}" in section
            assert f"item_{count + 1}" not in section


def test_verify_pages_match_both_catalogs() -> None:
    """The step count and the page keys stay in sync across locales."""
    assert connect_verify.VERIFY_STEPS == 6
    for locale in _LOCALES:
        verify = _catalog(locale, "connecting")["verify"]
        assert isinstance(verify, dict)
        for step in range(1, connect_verify.VERIFY_STEPS):
            for suffix in ("title", "body", "detail", "note"):
                assert f"page_{step}_{suffix}" in verify
        assert "why" in verify


def test_connect_button_revealed_only_on_the_final_step() -> None:
    """An owner cannot skip the moderation-scope page."""
    early = connect_verify_btn(4, "tc_verify", "tc_join", "tc_cancel", "en-US")
    final = connect_verify_btn(5, "tc_verify", "tc_join", "tc_cancel", "en-US")
    early_data = [b.callback_data for row in early.inline_keyboard for b in row]
    final_data = [b.callback_data for row in final.inline_keyboard for b in row]
    assert "tc_join" not in early_data
    assert "tc_join" in final_data


def test_verify_prompt_uses_rich_blocks_for_the_scope_page() -> None:
    """The moderation-scope page renders as real rich blocks."""
    flow = BuildConnection("TCF")
    text = flow.verify_prompt(4, "en-US")
    assert "<h2>" in text
    assert "<hr/>" in text
    assert "<p>" in text
