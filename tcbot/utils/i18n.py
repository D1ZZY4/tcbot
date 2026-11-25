# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""TOML-backed localization engine: catalog loading, lookup, and formatting."""

from __future__ import annotations

import html
import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

_HTML_ESCAPE = html.escape

# * All formatting is rich HTML from the helper/rich modules. Inline rich
# * primitives avoid importing tcbot.modules at catalog load time; heavier
# * helpers cache their lazy import on first use.
_USERNAME_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_]{5,32}$")

_mention_button_fn: Callable[[int, str], str] | None = None
_quote_fn: Callable[..., str] | None = None
_heading_fn: Callable[[object, int], str] | None = None
_bullet_list_fn: Callable[[list[str]], str] | None = None


def esc(text: object) -> str:
    """Escape untrusted text for a rich HTML field."""
    s = text if type(text) is str else str(text)
    if not s:
        return ""
    return _HTML_ESCAPE(s, quote=True)


def bold(text: object) -> str:
    """Render text in rich bold markup."""
    content = esc(text)
    return f"<b>{content}</b>" if content else ""


def italic(text: object) -> str:
    """Render text in rich italic markup."""
    content = esc(text)
    return f"<i>{content}</i>" if content else ""


def underline(text: object) -> str:
    """Render text in rich underline markup."""
    content = esc(text)
    return f"<u>{content}</u>" if content else ""


def strike(text: object) -> str:
    """Render text in rich strikethrough markup."""
    content = esc(text)
    return f"<s>{content}</s>" if content else ""


def code(text: object) -> str:
    """Render text as an inline rich code span."""
    content = esc(text)
    return f"<code>{content}</code>" if content else ""


def pre(text: object) -> str:
    """Render text as a rich preformatted block."""
    content = esc(text)
    return f"<pre><code>{content}</code></pre>" if content else ""


def link(text: object, url: str) -> str:
    """Render a rich hyperlink from text and a URL."""
    return f'<a href="{esc(url)}">{esc(text)}</a>'


def user_ref(user_id: int, name: str, username: str | None = None) -> str:
    """Render a native rich mention button for a user ID.

    Telegram has no dedicated mention button: the documented mechanism is a
    URL button carrying ``tg://user?id=``. Keeping the public signature here
    lets every existing catalog placeholder migrate in one place.
    """
    global _mention_button_fn
    if user_id <= 0:
        return bold(name or str(user_id))
    fn = _mention_button_fn
    if fn is None:
        from tcbot.modules.helper.rich.button import (  # noqa: PLC0415
            mention_button as _mention_button,
        )

        fn = _mention_button
        _mention_button_fn = fn
    return fn(user_id, name)


def safe_username(username: str | None) -> str | None:
    """Return ``username`` only when it matches a Telegram username shape."""
    if username and _USERNAME_RE.fullmatch(username):
        return username
    return None


def divider() -> str:
    """Render the shared rich horizontal rule."""
    return "<hr/>"


def quote(text: str, *, author: object | None = None) -> str:
    """Render a block quotation, with an optional attributed author."""
    global _quote_fn
    fn = _quote_fn
    if fn is None:
        from tcbot.modules.helper.rich.formats import quote as _quote  # noqa: PLC0415

        fn = _quote
        _quote_fn = fn
    return fn(text, author=author)


def heading(text: object, level: int = 2) -> str:
    """Render a rich section heading."""
    global _heading_fn
    fn = _heading_fn
    if fn is None:
        from tcbot.modules.helper.rich.formats import (  # noqa: PLC0415
            heading as _heading,
        )

        fn = _heading
        _heading_fn = fn
    return fn(text, level)


def subscript(text: object) -> str:
    """Render text as rich subscript."""
    content = esc(text)
    return f"<sub>{content}</sub>" if content else ""


def superscript(text: object) -> str:
    """Render text as rich superscript."""
    content = esc(text)
    return f"<sup>{content}</sup>" if content else ""


def bullet_list(lines: list[str]) -> str:
    """Render already-formatted lines as a rich bulleted block."""
    global _bullet_list_fn
    fn = _bullet_list_fn
    if fn is None:
        from tcbot.modules.helper.rich.list import (  # noqa: PLC0415
            bullet_list as _bullet_list,
        )

        fn = _bullet_list
        _bullet_list_fn = fn
    return fn([line for line in lines if line])


def section(title: str, body: str) -> str:
    """Render a titled section with the rich divider rule."""
    return f"{bold(title)}\n<hr/>\n{body}"


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


class I18nError(ValueError):
    """Programming error in translation usage: bad template or bad value.

    This is not a missing dictionary key. Inheriting from KeyError let callers
    with a legitimate ``except KeyError`` around a rendering step swallow a
    broken catalog template and report it as a data-parse failure, hiding the
    real defect. ValueError keeps those two failure modes distinct.
    """


_catalog: dict[str, dict[str, str]] = {}
_catalog_root: Path | None = None
_global_locale_cache: dict[str, str | None] = {}
_global_plans: dict[tuple[str, str, bool], _CompiledTemplate] = {}
_compiled_cache: dict[tuple[str, bool], _CompiledTemplate] = {}
_COMPILED_CACHE_MAX = 8192
_LOCALE_CACHE_MAX = 512


class _CompiledTemplate:
    """Pre-parsed template with pre-escaped static segments and field names."""

    __slots__ = ("field_count", "fields", "static")

    def __init__(self, static: tuple[str, ...], fields: tuple[str, ...]) -> None:
        self.static = static
        self.fields = fields
        self.field_count = len(fields)


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
        _global_locale_cache.clear()
        _global_plans.clear()
        for existing in _catalog:
            _global_locale_cache[existing] = existing
            _global_locale_cache[existing.lower()] = existing
        for alias, target in _LOCALE_ALIASES.items():
            resolved = _canonical_locale(target, _catalog)
            if resolved is not None:
                _global_locale_cache[alias] = resolved
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
    if catalog is _catalog:
        cached = _global_locale_cache.get(locale)
        if cached is not None or locale in _global_locale_cache:
            return cached
    wanted = locale.strip().lower()
    result: str | None = None
    for existing in catalog:
        if existing.lower() == wanted:
            result = existing
            break
    if result is None:
        alias_target = _LOCALE_ALIASES.get(wanted)
        if alias_target is not None:
            alias_lower = alias_target.lower()
            for existing in catalog:
                if existing.lower() == alias_lower:
                    result = existing
                    break
    if catalog is _catalog and len(_global_locale_cache) < _LOCALE_CACHE_MAX:
        _global_locale_cache[locale] = result
    return result


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
    val_type = type(value)
    if val_type is str:
        return _HTML_ESCAPE(value, quote=True) if escape else value  # type: ignore[arg-type]
    if val_type is Safe or isinstance(value, Safe):
        return str(value)
    if value is None:
        raise I18nError(f"i18n placeholder {name!r} got None; pass a real value")
    if val_type is int or val_type is bool or val_type is float:
        return str(value)
    text = str(value)
    return _HTML_ESCAPE(text, quote=True) if escape else text


def _compile_template(template: str, *, key: str, escape: bool) -> _CompiledTemplate:
    """Parse ``template`` once into pre-escaped static segments and field names."""
    static: list[str] = []
    fields: list[str] = []
    cur: list[str] = []

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
            cur.append(
                f"<code>{_HTML_ESCAPE(inner, quote=True)}</code>" if escape else inner
            )
            i = j + 1
        elif ch == "*":
            j = template.find("*", i + 1)
            if j < 0:
                raise I18nError(f"i18n template {key!r} has an unbalanced asterisk")
            inner = template[i + 1 : j]
            check_span(inner, "bold")
            if "`" in inner or "*" in inner or "~" in inner:
                raise I18nError(
                    f"i18n template {key!r} forbids nesting inside bold spans"
                )
            cur.append(f"<b>{_HTML_ESCAPE(inner, quote=True)}</b>" if escape else inner)
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
            cur.append(f"<i>{_HTML_ESCAPE(inner, quote=True)}</i>" if escape else inner)
            i = j + 1
        elif ch == "{":
            if template.startswith("{{", i):
                cur.append("{" if not escape else _HTML_ESCAPE("{", quote=True))
                i += 2
                continue
            j = template.find("}", i + 1)
            if j < 0:
                raise I18nError(f"i18n template {key!r} has an unbalanced brace")
            name = template[i + 1 : j]
            if not _FIELD_RE.match(name):
                raise I18nError(f"i18n template {key!r} must use bare {{name}} fields")
            static.append("".join(cur))
            cur.clear()
            fields.append(name)
            i = j + 1
        elif ch == "}":
            if template.startswith("}}", i):
                cur.append("}" if not escape else _HTML_ESCAPE("}", quote=True))
                i += 2
                continue
            raise I18nError(f"i18n template {key!r} has an unbalanced brace")
        else:
            # * Copy a maximal run of plain characters at once instead of
            # * appending one character at a time.
            next_special = n
            for marker in ("`", "*", "~", "{", "}"):
                pos = template.find(marker, i + 1)
                if 0 <= pos < next_special:
                    next_special = pos
            chunk = template[i:next_special]
            cur.append(_HTML_ESCAPE(chunk, quote=True) if escape else chunk)
            i = next_special
    static.append("".join(cur))
    return _CompiledTemplate(tuple(static), tuple(fields))


def _render_compiled(
    plan: _CompiledTemplate,
    kwargs: dict[str, object],
    *,
    key: str,
    escape: bool,
) -> str:
    """Render a compiled template with ``kwargs``."""
    fc = plan.field_count
    static = plan.static
    if fc == 0:
        if kwargs:
            for name, val in kwargs.items():
                if val is None:
                    raise I18nError(
                        f"i18n placeholder {name!r} got None; pass a real value"
                    )
        return static[0]
    fields = plan.fields
    if len(kwargs) != fc:
        for name, val in kwargs.items():
            if val is None:
                raise I18nError(
                    f"i18n placeholder {name!r} got None; pass a real value"
                )
    if fc == 1:
        f0 = fields[0]
        try:
            raw0 = kwargs[f0]
        except KeyError:
            raise I18nError(
                f"i18n template {key!r} missing value for {{{f0}}}"
            ) from None
        return f"{static[0]}{_prepare_value(f0, raw0, escape=escape)}{static[1]}"
    if fc == 2:
        f0, f1 = fields
        try:
            raw0 = kwargs[f0]
            raw1 = kwargs[f1]
        except KeyError as missing:
            raise I18nError(
                f"i18n template {key!r} missing value for {{{missing.args[0]}}}"
            ) from None
        v0 = _prepare_value(f0, raw0, escape=escape)
        v1 = _prepare_value(f1, raw1, escape=escape)
        return f"{static[0]}{v0}{static[1]}{v1}{static[2]}"
    if fc == 3:
        f0, f1, f2 = fields
        try:
            raw0 = kwargs[f0]
            raw1 = kwargs[f1]
            raw2 = kwargs[f2]
        except KeyError as missing:
            raise I18nError(
                f"i18n template {key!r} missing value for {{{missing.args[0]}}}"
            ) from None
        v0 = _prepare_value(f0, raw0, escape=escape)
        v1 = _prepare_value(f1, raw1, escape=escape)
        v2 = _prepare_value(f2, raw2, escape=escape)
        return f"{static[0]}{v0}{static[1]}{v1}{static[2]}{v2}{static[3]}"
    out: list[str] = [static[0]]
    for idx, fname in enumerate(fields):
        try:
            raw = kwargs[fname]
        except KeyError:
            raise I18nError(
                f"i18n template {key!r} missing value for {{{fname}}}"
            ) from None
        out.append(_prepare_value(fname, raw, escape=escape))
        out.append(static[idx + 1])
    return "".join(out)


def _render_template(
    template: str, prepared: dict[str, str], *, key: str, escape: bool
) -> str:
    """Substitute placeholders and resolve the strict mini-markup."""
    plan = _compile_template(template, key=key, escape=escape)
    if plan.field_count == 0:
        return plan.static[0]
    out: list[str] = [plan.static[0]]
    for idx, fname in enumerate(plan.fields):
        if fname not in prepared:
            raise I18nError(f"i18n template {key!r} missing value for {{{fname}}}")
        out.append(prepared[fname])
        out.append(plan.static[idx + 1])
    return "".join(out)


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
    escape = not plain
    if catalog is None:
        data = _catalog or _ensure_loaded()
        canonical = (
            DEFAULT_LOCALE
            if locale is None
            else (_canonical_locale(locale, data) or DEFAULT_LOCALE)
        )
        plan = _global_plans.get((canonical, key, escape))
        if plan is None:
            template = data.get(canonical, {}).get(key)
            if template is None:
                template = data.get(DEFAULT_LOCALE, {}).get(key)
            if template is None:
                log.error("i18n missing key %r (locale %r)", key, locale)
                return f"[{key}]" if plain else esc(f"[{key}]")
            plan = _compile_template(template, key=key, escape=escape)
            _global_plans[(canonical, key, escape)] = plan
        return _render_compiled(plan, kwargs, key=key, escape=escape)

    canonical = _canonical_locale(locale, catalog) or DEFAULT_LOCALE
    template = catalog.get(canonical, {}).get(key)
    if template is None:
        template = catalog.get(DEFAULT_LOCALE, {}).get(key)
    if template is None:
        log.error("i18n missing key %r (locale %r)", key, locale)
        return f"[{key}]" if plain else esc(f"[{key}]")
    cache_key = (template, escape)
    plan = _compiled_cache.get(cache_key)
    if plan is None:
        plan = _compile_template(template, key=key, escape=escape)
        if len(_compiled_cache) >= _COMPILED_CACHE_MAX:
            _compiled_cache.clear()
        _compiled_cache[cache_key] = plan
    return _render_compiled(plan, kwargs, key=key, escape=escape)


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
