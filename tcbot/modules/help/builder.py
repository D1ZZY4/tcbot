# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Help content builder: per-locale topic lists, name maps, and text helpers."""

from __future__ import annotations

import importlib

from tcbot import cfg
from tcbot.modules import ALL_MODULES
from tcbot.utils.formatter import bold, code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

log = get_logger(__name__)

# * Help runtime prose lives in help.toml [error]/[note]/[module]/
# * [section]/[not_found]/[group].


# ────────────────────── Help Content Builder ────────────────────── #


def _builder_help(
    locale: str | None = None,
) -> dict[str, tuple[str, str, list[tuple[str, str]]]]:
    """Collect help content from every loaded module in the given locale.

    Returns a dict keyed by ``help_<module>`` mapping to
    ``(display_name, overview_text, sections)``. Modules without a
    ``get_help(locale)`` builder (non-help modules) are simply skipped.
    """
    content: dict[str, tuple[str, str, list[tuple[str, str]]]] = {}
    for mod_name in ALL_MODULES:
        try:
            mod = importlib.import_module(f"tcbot.modules.{mod_name}")
            get_help = getattr(mod, "get_help", None)
            if not callable(get_help):
                continue
            try:
                h: object = get_help(locale)
            except Exception:
                h = None
            if isinstance(h, dict):
                content[f"help_{mod_name}"] = (
                    h["name"],
                    h["overview"],
                    list(h.get("sections", [])),
                )
        except Exception as exc:
            log.warning("Could not read help from %s: %s", mod_name, exc)
    return content


# ─────────────────────── Module-Level State ─────────────────────── #

HELP_CONTENT = _builder_help()

# * Sorted by display name (case-insensitive)
_TOPICS_SORTED: list[tuple[str, str]] = sorted(
    ((entry[0], key) for key, entry in HELP_CONTENT.items()),
    key=lambda t: t[0].lower(),
)

# * Menu-path topics; an explicit copy so a future mutation of one list
# * cannot silently reshape the other path's keyboard.
HELP_TOPICS_MENU: list[tuple[str, str]] = list(_TOPICS_SORTED)

# * Command-path topics; callback keys become "helpc_<mod>"
HELP_TOPICS_CMD: list[tuple[str, str]] = [
    (name, "helpc_" + key[5:]) for name, key in _TOPICS_SORTED
]

# * Module name → help key mapping for /help <module> lookup
# * (default-locale snapshot; per-request paths rebuild for the tapper's
# * locale via _module_map_for_locale below).
_MODULE_NAME_MAP: dict[str, str] = {}
for _key, _entry in HELP_CONTENT.items():
    _module_slug = _key[5:]
    _MODULE_NAME_MAP[_module_slug.lower()] = _key
    _MODULE_NAME_MAP[_entry[0].lower()] = _key


def _topics_for_locale(locale: str | None, *, menu: bool) -> list[tuple[str, str]]:
    """Build the help-index topic list in ``locale`` (names + callbacks).

    The module-level ``HELP_TOPICS_*`` lists are default-locale snapshots
    for import-time use; index renders call this so topic names follow the
    tapper's locale like every other keyboard.
    """
    content = _builder_help(locale)
    ordered = sorted(
        ((entry[0], key) for key, entry in content.items()),
        key=lambda item: item[0].lower(),
    )
    if menu:
        return list(ordered)
    return [(name, "helpc_" + key[5:]) for name, key in ordered]


def _module_map_for_locale(locale: str | None) -> dict[str, str]:
    """Build the module-name → help-key map in ``locale`` for /help <name>."""
    mapping: dict[str, str] = {}
    for key, entry in _builder_help(locale).items():
        slug = key[5:]
        mapping[slug.lower()] = key
        mapping[entry[0].lower()] = key
    return mapping


def _help_index_text(botname: str, locale: str | None = None) -> str:
    """Build the help index header for the given plain-text bot display name."""
    # * Title renders plain then bolds outside: the engine would double
    # * escape the name if it escaped first, and plain alone would leave
    # * a markup-bearing bot name unescaped. bold() escapes exactly once.
    return t(
        "help.index.body",
        locale,
        title=Safe(bold(t("help.index.title", locale, botname=botname, plain=True))),
        community=cfg.community_name,
    )


# ──────────────────────── Shared Renderers ──────────────────────── #


def _prefix_note(locale: str | None = None) -> str:
    """Render the command-prefix footer note in ``locale``.

    Prefixes come from frozen env config and never change at runtime, but
    the surrounding prose is translated, so this renders per request
    instead of once at import. The leading newline separates the note
    from the overview.
    """
    return "\n" + t(
        "help.note.prefixes",
        locale,
        prefixes=Safe(" ".join(code(p) for p in cfg.prefixes)),
    )


def _section_buttons(
    mod_slug: str,
    sections: list[tuple[str, str]],
    *,
    is_menu_path: bool,
) -> list[tuple[str, str]]:
    """Build (label, callback_data) pairs for each section."""
    prefix = "helps_" if is_menu_path else "helpcs_"
    return [
        (label, f"{prefix}{mod_slug}:{idx}") for idx, (label, _) in enumerate(sections)
    ]


def _module_text(name: str, overview: str, locale: str | None = None) -> str:
    """Compose the module-overview MarkdownV2 body."""
    return t(
        "help.module.body",
        locale,
        title=Safe(bold(t("help.module.title", locale, name=name, plain=True))),
        overview=Safe(overview),
        note=Safe(_prefix_note(locale)),
    )
