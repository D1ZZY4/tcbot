# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""TOML-backed localization engine: catalog loading, lookup, and formatting."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from tcbot.utils.logger import get_logger

# * All formatting is rich HTML from the helper/messages rich modules. The
# * imports are lazy (inside the helpers) because that package imports i18n
# * back; importing at module load would create a cycle.
_USERNAME_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_]{5,32}$")


def esc(text: object) -> str:
    """Escape untrusted text for a rich HTML field."""
    from tcbot.modules.helper.messages.rich_style import esc as _esc  # noqa: PLC0415

    return _esc(text)


def bold(text: object) -> str:
    """Render text in rich bold markup."""
    from tcbot.modules.helper.messages.rich_style import bold as _bold  # noqa: PLC0415

    return _bold(text)


def italic(text: object) -> str:
    """Render text in rich italic markup."""
    from tcbot.modules.helper.messages.rich_style import italic as _italic  # noqa: PLC0415

    return _italic(text)


def underline(text: object) -> str:
    """Render text in rich underline markup."""
    from tcbot.modules.helper.messages.rich_style import underline as _underline  # noqa: PLC0415

    return _underline(text)


def strike(text: object) -> str:
    """Render text in rich strikethrough markup."""
    from tcbot.modules.helper.messages.rich_style import strike as _strike  # noqa: PLC0415

    return _strike(text)


def code(text: object) -> str:
    """Render text as an inline rich code span."""
    from tcbot.modules.helper.messages.rich_format import code as _code  # noqa: PLC0415

    return _code(text)


def pre(text: object) -> str:
    """Render text as a rich preformatted block."""
    from tcbot.modules.helper.messages.rich_format import pre as _pre  # noqa: PLC0415

    return _pre(text)


def link(text: object, url: str) -> str:
    """Render a rich hyperlink from text and a URL."""
    from tcbot.modules.helper.messages.rich_link import link as _link  # noqa: PLC0415

    return _link(text, url)


def user_ref(user_id: int, name: str, username: str | None = None) -> str:
    """Render a rich, ID-based mention of a user."""
    from tcbot.modules.helper.messages.rich_link import user_ref as _user_ref  # noqa: PLC0415

    return _user_ref(user_id, name)


def safe_username(username: str | None) -> str | None:
    """Return ``username`` only when it matches a Telegram username shape."""
    if username and _USERNAME_RE.fullmatch(username):
        return username
    return None


def divider() -> str:
    """Render the shared rich horizontal rule."""
    from tcbot.modules.helper.messages.rich_format import divider as _divider  # noqa: PLC0415

    return _divider()


def quote(text: str, *, author: object | None = None) -> str:
    """Render a block quotation, with an optional attributed author."""
    from tcbot.modules.helper.messages.rich_format import quote as _quote  # noqa: PLC0415

    return _quote(text, author=author)


def heading(text: object, level: int = 2) -> str:
    """Render a rich section heading."""
    from tcbot.modules.helper.messages.rich_format import (  # noqa: PLC0415
        heading as _heading,
    )

    return _heading(text, level)


def subscript(text: object) -> str:
    """Render text as rich subscript."""
    from tcbot.modules.helper.messages.rich_style import (  # noqa: PLC0415
        subscript as _subscript,
    )

    return _subscript(text)


def superscript(text: object) -> str:
    """Render text as rich superscript."""
    from tcbot.modules.helper.messages.rich_style import (  # noqa: PLC0415
        superscript as _superscript,
    )

    return _superscript(text)


def bullet_list(lines: list[str]) -> str:
    """Render already-formatted lines as a rich bulleted block."""
    from tcbot.modules.helper.messages.rich_list import bullet_list as _bullet_list  # noqa: PLC0415

    return _bullet_list([line for line in lines if line])


def section(title: str, body: str) -> str:
    """Render a titled section with the rich divider rule."""
    return f"{bold(title)}\n{divider()}\n{body}"


log = get_logger(__name__)

# * BCP 47 shaped default; every other locale falls back to it per key.
DEFAULT_LOCALE: str = "en-US"

# * Legacy code retained for stored per-user and per-group preferences plus
# * in-flight language callbacks: ``id`` still resolves to the Indonesian
# * catalog after its rename to ``id-ID``. Keys are lowercase; the alias
# * target is matched case-insensitively against the catalog, so only an
# * ``id-ID`` catalog keeps the alias alive.
_LOCALE_ALIASES: dict[str, str] = {"id": "id-ID"}

# * Mini-markup field names: bare identifiers only, so format specs and
# * conversions can never smuggle unescaped content past the renderer.
_FIELD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class Safe(str):
    """Pre-formatted fragment exempt from placeholder escaping.

    Wrap ``user_ref()``/``code()``/``bold()`` output (or any already-safe
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

    File name is the key prefix: ``banning.toml`` holding ``done`` registers
    ``banning.done``. Malformed TOML raises :class:`I18nError` immediately so
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


def available_locales(catalog: dict[str, dict[str, str]] | None = None) -> list[str]:
    """Return sorted locale codes present in the catalog."""
    data = catalog if catalog is not None else _ensure_loaded()
    return sorted(data)


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
    alias_target = _LOCALE_ALIASES.get(wanted)
    if alias_target is not None:
        for existing in catalog:
            if existing.lower() == alias_target.lower():
                return existing
    return None


def is_known_locale(
    locale: str | None, catalog: dict[str, dict[str, str]] | None = None
) -> bool:
    """Return True when ``locale`` has a catalog (case-insensitive).

    Aliases count as known: the engine resolves ``id`` to ``id-ID``, so an
    in-flight callback carrying the alias must not be rejected as unknown.
    """
    if not locale:
        return False
    data = catalog if catalog is not None else _ensure_loaded()
    return _canonical_locale(locale, data) is not None


def canonical_locale(
    locale: str | None, catalog: dict[str, dict[str, str]] | None = None
) -> str | None:
    """Return the catalog spelling of *locale*, or None when it is unknown."""
    data = catalog if catalog is not None else _ensure_loaded()
    return _canonical_locale(locale, data)


def display_name(locale: str, catalog: dict[str, dict[str, str]] | None = None) -> str:
    """Return the human-readable name of ``locale`` for buttons and confirmations."""
    data = catalog if catalog is not None else _ensure_loaded()
    canonical = _canonical_locale(locale, data)
    if canonical is None:
        return locale
    return data[canonical].get("button.language_name", canonical)


def _prepare_value(name: str, value: object, *, escape: bool) -> str:
    """Render one placeholder value for the requested mode.

    Raw strings are escaped in rich mode and verbatim in plain
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
    """Substitute placeholders and resolve the strict mini-markup.

    In rich mode (``escape=True``) literal text is HTML-escaped and the
    `` `code` `` / ``*bold*`` / ``~italic~`` spans become ``<code>`` / ``<b>``
    / ``<i>`` tags. Plain mode (``plain=True``) keeps raw catalog text for
    callback alerts, which Telegram never parses.
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
            parts.append(f"<code>{esc(inner)}</code>" if escape else inner)
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
            parts.append(f"<b>{esc(inner)}</b>" if escape else inner)
            i = j + 1
        elif ch == "~":
            j = template.find("~", i + 1)
            if j < 0:
                raise I18nError(f"i18n template {key!r} has an unbalanced tilde")
            inner = template[i + 1 : j]
            check_span(inner, "italic")
            if "`" in inner or "*" in inner or "~" in inner:
                raise I18nError(
                    f"i18n template {key!r} forbids nesting inside italic spans"
                )
            flush_literal()
            parts.append(f"<i>{esc(inner)}</i>" if escape else inner)
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

    Templates are stored raw with `` `code` `` and ``*bold*`` mini-markup.
    Rich mode renders HTML-escaped text with real tags; ``plain=True`` keeps
    raw text for callback alerts, which Telegram never parses.
    Unknown locales fall back to :data:`DEFAULT_LOCALE`; keys missing in
    the locale fall back per key. A key missing everywhere is a
    programming error: it is logged and returned as ``[key]``.
    """
    if vargs:
        raise I18nError(f"i18n key {key!r} takes keyword placeholders only")
    data = catalog if catalog is not None else _ensure_loaded()
    canonical = _canonical_locale(locale, data) or DEFAULT_LOCALE
    template = data.get(canonical, {}).get(key)
    if template is None:
        template = data.get(DEFAULT_LOCALE, {}).get(key)
    if template is None:
        log.error("i18n missing key %r (locale %r)", key, locale)
        return f"[{key}]" if plain else esc(f"[{key}]")
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
    community_locale: str | None = None,
    explicit: str | None = None,
    catalog: dict[str, dict[str, str]] | None = None,
) -> str:
    """Resolve the effective locale for one message with explicit precedence.

    ``explicit`` always wins. Otherwise private chats use the user locale
    and group-like chats use the group locale, so a shared audience always
    reads one language. The community default is the next tier, and
    :data:`DEFAULT_LOCALE` is the last. Unknown or absent values fall
    through to the next tier; resolution never raises.
    """
    data = catalog if catalog is not None else _ensure_loaded()
    for candidate in (
        explicit,
        user_locale if chat_type == "private" else group_locale,
        community_locale,
    ):
        canonical = _canonical_locale(candidate, data)
        if canonical is not None:
            return canonical
    return DEFAULT_LOCALE
