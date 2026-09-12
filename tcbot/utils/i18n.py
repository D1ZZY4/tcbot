# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""TOML-backed localization engine: catalog loading, lookup, and formatting."""

from __future__ import annotations

import logging
import re
import string
import tomllib
from pathlib import Path

from tcbot.utils.formatter import esc

log = logging.getLogger(__name__)

# * BCP 47 shaped default; every other locale falls back to it per key.
DEFAULT_LOCALE: str = "en-US"

# * MarkdownV2 specials that must be backslash-escaped in regular text.
# * Mirrors the formatter contract without importing its private table.
_V2_SPECIAL: frozenset[str] = frozenset("_*[]()~`>#+-=|{}.!")

# * Mini-markup field names: bare identifiers only, so format specs and
# * conversions can never smuggle unescaped content past the renderer.
_FIELD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class Safe(str):
    """Pre-formatted fragment exempt from placeholder escaping.

    Wrap ``mention()``/``code()``/``bold()`` output (or any already-safe
    markup) so :func:`t` interpolates it verbatim instead of escaping it.
    """


class I18nError(KeyError):
    """Programming error in translation usage: bad template or bad value."""


_catalog: dict[str, dict[str, str]] = {}
_catalog_root: Path | None = None


def _default_root() -> Path:
    """Return the ``i18n/`` directory at the project root."""
    return Path(__file__).resolve().parent.parent.parent / "i18n"


def _flatten(prefix: str, node: object, out: dict[str, str], *, source: str) -> None:
    """Flatten one TOML document into dotted keys under ``prefix``."""
    if isinstance(node, dict):
        for name, value in node.items():
            _flatten(
                f"{prefix}.{name}" if prefix else str(name), value, out, source=source
            )
    elif isinstance(node, str):
        out[prefix] = node
    else:
        raise I18nError(f"i18n value for {prefix!r} in {source} must be a string")


def load_catalog(root: Path | None = None) -> dict[str, dict[str, str]]:
    """Load every locale under ``root`` (default: project ``i18n/``).

    File name is the key prefix: ``ban.toml`` holding ``done`` registers
    ``ban.done``. Malformed TOML raises :class:`I18nError` immediately so
    a broken catalog fails fast at startup instead of mid-conversation.
    """
    base = root if root is not None else _default_root()
    if not base.is_dir():
        raise I18nError(f"i18n catalog directory missing: {base}")
    loaded: dict[str, dict[str, str]] = {}
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        tables: dict[str, str] = {}
        for path in sorted(entry.glob("*.toml")):
            try:
                with path.open("rb") as fh:
                    doc = tomllib.load(fh)
            except tomllib.TOMLDecodeError as exc:
                raise I18nError(f"malformed TOML in {path}: {exc}") from exc
            _flatten(path.stem, doc, tables, source=str(path))
        if tables:
            loaded[entry.name] = tables
    if DEFAULT_LOCALE not in loaded:
        raise I18nError(f"default locale {DEFAULT_LOCALE!r} has no catalog in {base}")
    return loaded


def _ensure_loaded() -> dict[str, dict[str, str]]:
    """Return the process-wide catalog, loading it on first use."""
    global _catalog, _catalog_root
    if not _catalog:
        _catalog_root = _default_root()
        _catalog = load_catalog(_catalog_root)
        log.info(
            "i18n catalog loaded: %s",
            ", ".join(f"{loc} ({len(keys)})" for loc, keys in sorted(_catalog.items())),
        )
    return _catalog


def reload_catalog(root: Path | None = None) -> None:
    """Reload the process-wide catalog, primarily for tests."""
    global _catalog, _catalog_root
    _catalog_root = root if root is not None else _default_root()
    _catalog = load_catalog(_catalog_root)


def available_locales(catalog: dict[str, dict[str, str]] | None = None) -> list[str]:
    """Return sorted locale codes present in the catalog."""
    data = catalog if catalog is not None else _ensure_loaded()
    return sorted(data)


def is_known_locale(
    locale: str | None, catalog: dict[str, dict[str, str]] | None = None
) -> bool:
    """Return True when ``locale`` has a catalog (case-insensitive)."""
    if not locale:
        return False
    data = catalog if catalog is not None else _ensure_loaded()
    wanted = locale.strip()
    return any(existing.lower() == wanted.lower() for existing in data)


def _canonical_locale(
    locale: str | None, catalog: dict[str, dict[str, str]]
) -> str | None:
    """Return the catalog spelling of ``locale``, or None when unknown."""
    if not locale:
        return None
    wanted = locale.strip().lower()
    for existing in catalog:
        if existing.lower() == wanted:
            return existing
    return None


def display_name(locale: str, catalog: dict[str, dict[str, str]] | None = None) -> str:
    """Return the human-readable name of ``locale`` for buttons and confirmations."""
    data = catalog if catalog is not None else _ensure_loaded()
    canonical = _canonical_locale(locale, data)
    if canonical is None:
        return locale
    return data[canonical].get("button.language_name", canonical)


def _prepare_value(name: str, value: object, *, escape: bool) -> str:
    """Render one placeholder value for the requested mode.

    Raw strings are escaped in MarkdownV2 mode and verbatim in plain
    mode; :class:`Safe` fragments (helper markup) always pass through.
    """
    if isinstance(value, Safe):
        return str(value)
    if isinstance(value, str):
        return esc(value) if escape else value
    if value is None:
        raise I18nError(f"i18n placeholder {name!r} got None; pass a real value")
    if isinstance(value, bool | int | float):
        return str(value)
    text = str(value)
    return esc(text) if escape else text


def _render_template(
    template: str, prepared: dict[str, str], *, key: str, escape: bool
) -> str:
    """Substitute ``{name}`` placeholders and resolve mini-markup.

    Only two markup forms exist, both strict: ```code` `` spans and
    ``*bold*`` spans must be non-empty, balanced, unnested, and free of
    braces (placeholder ambiguity). Anything else raises
    :class:`I18nError` so malformed translator markup fails tests,
    never production sends. Span contents escape exactly what
    MarkdownV2 requires inside them (code: backtick/backslash only;
    bold: full text set); plain mode strips the markers.
    """
    parts: list[str] = []
    literal: list[str] = []

    def flush_literal() -> None:
        if literal:
            text = "".join(literal)
            parts.append(esc(text) if escape else text)
            literal.clear()

    def check_span(inner: str, kind: str) -> None:
        if not inner:
            raise I18nError(f"i18n template {key!r} has an empty {kind} span")
        if "{" in inner or "}" in inner:
            raise I18nError(f"i18n template {key!r} forbids braces inside {kind} spans")

    i, n = 0, len(template)
    while i < n:
        ch = template[i]
        if ch == "`":
            j = template.find("`", i + 1)
            if j < 0:
                raise I18nError(f"i18n template {key!r} has an unbalanced backtick")
            inner = template[i + 1 : j]
            check_span(inner, "code")
            flush_literal()
            if escape:
                parts.append(f"`{inner.replace(chr(92), chr(92) * 2)}`")
            else:
                parts.append(inner)
            i = j + 1
        elif ch == "*":
            j = template.find("*", i + 1)
            if j < 0:
                raise I18nError(f"i18n template {key!r} has an unbalanced asterisk")
            inner = template[i + 1 : j]
            check_span(inner, "bold")
            if "`" in inner or "*" in inner:
                raise I18nError(
                    f"i18n template {key!r} forbids nesting inside bold spans"
                )
            flush_literal()
            parts.append(f"*{esc(inner)}*" if escape else inner)
            i = j + 1
        elif ch == "{":
            if template.startswith("{{", i):
                literal.append("{")
                i += 2
                continue
            j = template.find("}", i + 1)
            if j < 0:
                raise I18nError(f"i18n template {key!r} has an unbalanced brace")
            name = template[i + 1 : j]
            if not _FIELD_RE.match(name):
                raise I18nError(f"i18n template {key!r} must use bare {{name}} fields")
            if name not in prepared:
                raise I18nError(f"i18n template {key!r} missing value for {{{name}}}")
            flush_literal()
            parts.append(prepared[name])
            i = j + 1
        elif ch == "}":
            if template.startswith("}}", i):
                literal.append("}")
                i += 2
                continue
            raise I18nError(f"i18n template {key!r} has an unbalanced brace")
        else:
            literal.append(ch)
            i += 1
    flush_literal()
    return "".join(parts)


def t(
    key: str,
    locale: str | None = None,
    catalog: dict[str, dict[str, str]] | None = None,
    *vargs: object,
    plain: bool = False,
    **kwargs: object,
) -> str:
    """Render ``key`` for ``locale`` with safe placeholder interpolation.

    Templates are stored raw (no manual backslashes): literal segments
    are escaped here in MarkdownV2 mode and left verbatim with
    ``plain=True`` (callback alerts, which Telegram never parses).
    Templates may also use strict mini-markup (```code` `` and
    ``*bold*`` spans, balanced and unnested); malformed markup raises
    :class:`I18nError`.
    Unknown locales fall back to :data:`DEFAULT_LOCALE`; keys missing in
    the locale fall back per key. A key missing everywhere is a
    programming error: it is logged and returned as ``[key]`` (never an
    empty string, never an exception into the handler).
    """
    if vargs:
        raise I18nError(f"i18n key {key!r} takes keyword placeholders only")
    data = catalog if catalog is not None else _ensure_loaded()
    canonical = _canonical_locale(locale, data) or DEFAULT_LOCALE
    template = data.get(canonical, {}).get(key, data[DEFAULT_LOCALE].get(key))
    if template is None:
        log.error("i18n missing key %r (locale %r)", key, locale)
        return f"[{key}]"
    escape = not plain
    prepared = {
        name: _prepare_value(name, value, escape=escape)
        for name, value in kwargs.items()
    }
    return _render_template(template, prepared, key=key, escape=escape)


def resolve_locale(
    *,
    chat_type: str = "private",
    user_locale: str | None = None,
    group_locale: str | None = None,
    explicit: str | None = None,
    catalog: dict[str, dict[str, str]] | None = None,
) -> str:
    """Resolve the effective locale for one message with explicit precedence.

    ``explicit`` always wins. Otherwise private chats use the user locale
    and group-like chats use the group locale, so a shared audience always
    reads one language. Unknown or absent values fall through to
    :data:`DEFAULT_LOCALE`; resolution never raises.
    """
    data = catalog if catalog is not None else _ensure_loaded()
    for candidate in (
        explicit,
        user_locale if chat_type == "private" else group_locale,
    ):
        canonical = _canonical_locale(candidate, data)
        if canonical is not None:
            return canonical
    return DEFAULT_LOCALE


def placeholders(template: str) -> set[str]:
    """Return the ``{name}`` placeholders used by a template."""
    names: set[str] = set()
    for _, name, _, _ in string.Formatter().parse(template):
        if name:
            names.add(name.split(".", 1)[0].split("[", 1)[0])
    return names


def find_unescaped(text: str) -> list[str]:
    """Return descriptions of unescaped MarkdownV2 specials in rendered text.

    Used to validate catalog templates after dummy interpolation: a
    shipped template must render clean, since translators cannot be
    expected to debug entity errors.
    """
    problems: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in _V2_SPECIAL:
            if ch == "\\" and i + 1 < n and text[i + 1] in _V2_SPECIAL:
                i += 1
            else:
                backslashes = 0
                j = i - 1
                while j >= 0 and text[j] == "\\":
                    backslashes += 1
                    j -= 1
                if backslashes % 2 == 0:
                    context = text[max(0, i - 14) : i + 8].replace("\n", "\\n")
                    problems.append(f"unescaped {ch!r} near ...{context}...")
        i += 1
    return problems
