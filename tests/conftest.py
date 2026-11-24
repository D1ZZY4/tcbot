# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared pytest fixtures: mirror production logging startup for every test session."""

from __future__ import annotations

import dataclasses
import functools
import importlib
import inspect
import os
import pkgutil
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

# * Dummy import-time env: tcbot/__init__ loads Configs at import, so the
# * suite must not depend on CI-only env to collect. setdefault keeps real
# * CI/local values when already present.
os.environ.setdefault("BOT_TOKEN", "000000:dummy-token-for-lint000000000000000")
# * The dummy URL points at a port nothing listens on: the unit tests
# * never open a connection, so the placeholder must not be able to reach
# * a real server.
os.environ.setdefault(
    "DATABASE_URL", "postgresql://tcbot:dummy@127.0.0.1:1/tcbot_placeholder"
)
os.environ.setdefault("OWNER_ID", "1")
# * A ban cannot be filed without an evidence destination, so the suite
# * supplies a throwaway proof chat like a deployment would.
os.environ.setdefault("PROOFS", "-1000000000001")

import pytest
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import tcbot.modules as modules
from tcbot import cfg
from tcbot.database import redis_client as redis_client_mod
from tcbot.database.cache import singletons, twolevel
from tcbot.utils.logger import setup as setup_logging
from tests.postgres_support import (
    build_test_schema,
    drop_test_schema,
    require_test_database,
    reset_postgres_circuit,
    use_test_engine,
)


# * Most tests predate the Kurigram migration and still split an update and
# * a context into two objects. The application now owns one Ctx. Adapt those
# * doubles on the test side only, so production stays free of framework
# * compatibility layers while the existing assertions keep exercising it.
def _provided(value: Any, default: Any) -> Any:
    """Keep an explicitly empty double value instead of replacing it."""
    return default if value is None else value


def _is_ctx_like(value: Any) -> bool:
    """Check whether a value is a legacy context double."""
    return isinstance(value, _LegacyCtx) or any(
        hasattr(value, name)
        for name in ("bot", "client", "user_data", "chat_data", "bot_data", "args")
    )


def _is_ctx_side(value: Any) -> bool:
    """Check whether a value can be the context half of a legacy pair."""
    return value is None or _is_ctx_like(value) or isinstance(value, SimpleNamespace)


class _LegacyCtx:
    """Duck-typed Ctx built from a legacy update/context pair."""

    def __init__(self, update: Any, ctx: Any = None) -> None:
        """Combine the two doubles into the surface production handlers read."""
        if ctx is None and _is_ctx_like(update):
            update, ctx = None, update
        self._update = update
        self._ctx = ctx
        self.client = getattr(ctx, "bot", None) or getattr(update, "bot", None)
        self.bot = self.client
        # * An empty dict is a live shared payload, not a missing one.
        self.user_data = _provided(getattr(ctx, "user_data", None), {})
        self.chat_data = _provided(getattr(ctx, "chat_data", None), {})
        self.bot_data = _provided(getattr(ctx, "bot_data", None), {})
        self.args = tuple(_provided(getattr(ctx, "args", None), ()))
        self.update_id = _provided(getattr(update, "update_id", None), 0)

    @property
    def effective_user(self) -> Any:
        """Return the acting user from either double."""
        for source in (self._update, self._ctx):
            found = getattr(source, "effective_user", None) or getattr(
                source, "from_user", None
            )
            if found is not None:
                return found
        return None

    @property
    def effective_chat(self) -> Any:
        """Return the chat from either double."""
        for source in (self._update, self._ctx):
            found = getattr(source, "effective_chat", None) or getattr(
                getattr(source, "effective_message", None), "chat", None
            )
            if found is not None:
                return found
        return None

    def _from_sources(self, name: str) -> Any:
        """Read a surface from the update first, then the context double."""
        for source in (self._update, self._ctx):
            found = getattr(source, name, None)
            if found is not None:
                return found
        return None

    @property
    def effective_message(self) -> Any:
        """Return the message, including a callback's host message."""
        return self._from_sources("effective_message") or self._from_sources("message")

    @property
    def callback_query(self) -> Any:
        """Return the callback query when the update carries one."""
        return self._from_sources("callback_query")

    @property
    def chat_member(self) -> Any:
        """Return the chat-member update when the update carries one."""
        return (
            self._from_sources("my_chat_member")
            or self._from_sources("chat_member")
            or (self._update if hasattr(self._update, "old_chat_member") else None)
        )

    @property
    def chat_join_request(self) -> Any:
        """Return the join request when the update carries one."""
        return self._from_sources("chat_join_request") or (
            self._update if hasattr(self._update, "invite_link") else None
        )

    async def answer(
        self, text: str | None = None, *, show_alert: bool = False
    ) -> None:
        """Acknowledge a legacy callback query once."""
        query = self.callback_query
        if query is not None:
            await query.answer(text, show_alert=show_alert)


def _is_update_like(value: Any) -> bool:
    """Check whether a value is a legacy update double."""
    return any(
        hasattr(value, name)
        for name in (
            "effective_message",
            "effective_user",
            "callback_query",
            "from_user",
            "my_chat_member",
            "chat_member",
            "chat",
            "message_id",
        )
    )


def _adapt_legacy(func: Any, ctx_index: int, owner: type | None = None) -> Any:
    """Accept a legacy (update, ctx) call and forward one Ctx to *func*."""

    def _call_args(args: tuple[Any, ...]) -> tuple[Any, ...]:
        if owner is not None and args and isinstance(args[0], owner):
            # * A function installed on a class receives ``self`` explicitly.
            return (args[0], *_call_args(args[1:]))
        if len(args) <= ctx_index + 1:
            return args
        first, second = args[ctx_index], args[ctx_index + 1]
        if isinstance(first, _LegacyCtx) or isinstance(second, _LegacyCtx):
            return args
        # * Migrated helpers take (ctx, args, bot); a list or scalar second
        # * argument is real data, never a legacy context double.
        if isinstance(second, (list, tuple, dict, set, str, int, float, bool, bytes)):
            return args
        if _is_update_like(first) and _is_ctx_side(second):
            update, legacy_ctx = first, second
        elif _is_update_like(second) and _is_ctx_side(first):
            update, legacy_ctx = second, first
        elif _is_ctx_like(first):
            # * A lone ctx double still needs the effective_* surface.
            return (
                *args[:ctx_index],
                _LegacyCtx(None, first),
                *args[ctx_index + 1 :],
            )
        else:
            return args
        return (
            *args[:ctx_index],
            _LegacyCtx(update, legacy_ctx),
            *args[ctx_index + 2 :],
        )

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*_call_args(args), **kwargs)

        _async_wrapper._legacy_adapted = True  # type: ignore[attr-defined]
        return _async_wrapper

    @functools.wraps(func)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*_call_args(args), **kwargs)

    _wrapper._legacy_adapted = True  # type: ignore[attr-defined]
    return _wrapper


def _install_legacy_adapter() -> None:
    """Wrap application callables that take a single ``ctx`` argument."""
    for info in pkgutil.walk_packages(modules.__path__, "tcbot.modules."):
        module = importlib.import_module(info.name)
        for name, func in list(vars(module).items()):
            if name.startswith("__") or not callable(func):
                continue
            target = inspect.unwrap(func)
            try:
                params = [
                    p
                    for p in inspect.signature(target).parameters.values()
                    if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                ]
            except TypeError, ValueError:
                continue
            names = [p.name for p in params]
            if "ctx" not in names:
                continue
            index = names.index("ctx")
            if index not in (0, 1):
                continue
            setattr(module, name, _adapt_legacy(func, index))
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module.__name__:
                continue
            for name, method in list(vars(cls).items()):
                if name.startswith("__") or not callable(method):
                    continue
                target = inspect.unwrap(method)
                try:
                    names = [
                        p.name
                        for p in inspect.signature(target).parameters.values()
                        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                    ]
                except TypeError, ValueError:
                    continue
                if len(names) < 2 or names[0] != "self" or names[1] != "ctx":
                    continue
                # * Bound methods receive no self, so ctx is argument 0.
                setattr(cls, name, _adapt_legacy(method, 0, cls))


_install_legacy_adapter()

# * Legacy tests call inspect.unwrap(fn) to reach an undecorated handler body.
# * The adapter is their new calling surface, so unwrap must stop at it.
_original_unwrap = inspect.unwrap


def _unwrap_adapted(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Keep the legacy adapter when a test unwraps a decorated handler."""
    if getattr(func, "_legacy_adapted", False):
        return func
    return _original_unwrap(func, *args, **kwargs)


inspect.unwrap = _unwrap_adapted


def _button_dict(self: InlineKeyboardButton) -> dict[str, object]:
    """Shallow dict projection of a Kurigram button for keyboard assertions."""
    result: dict[str, object] = {"text": self.text}
    for name in ("callback_data", "url"):
        value = getattr(self, name, None)
        if value is not None:
            result[name] = value
    style = getattr(self, "style", None)
    if style is not None:
        result["style"] = style
    return result


def _markup_dict(self: InlineKeyboardMarkup) -> dict[str, object]:
    """Shallow dict projection of a Kurigram markup for keyboard assertions."""
    return {
        "inline_keyboard": [
            [_button_dict(b) for b in row] for row in self.inline_keyboard
        ]
    }


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


# * Keyboard assertions compare dicts while production builders return real
# * Kurigram button objects, so the projection keeps the enum-valued style.
InlineKeyboardButton.to_dict = _button_dict  # type: ignore[attr-defined]
InlineKeyboardMarkup.to_dict = _markup_dict  # type: ignore[attr-defined]


def _payload_text(payload: Any) -> str:
    """Read the text of a Kurigram rich payload for legacy doubles."""
    if isinstance(payload, dict):
        return str(payload.get("html", ""))
    return str(getattr(payload, "html", None) or payload)


def _patch_fake_edit(cls: type, name: str = "edit_message_text") -> None:
    """Let legacy doubles accept Kurigram's rich edit signature."""
    original = getattr(cls, name)

    async def _edit(self: Any, *args: Any, **kwargs: Any) -> Any:
        payload = kwargs.get("rich_message")
        if payload is not None:
            params = inspect.signature(original).parameters
            if "rich_message" not in params:
                kwargs.pop("rich_message")
                args = (*args[:2], _payload_text(payload))
        return await original(self, *args, **kwargs)

    setattr(cls, name, _edit)  # type: ignore[attr-defined]


async def _fake_reply_rich(self: Any, payload: Any, **kwargs: Any) -> Any:
    """Adapt a legacy reply_text double to the rich send surface."""
    reply = getattr(self, "reply_text", None)
    if reply is None:
        return None
    return await reply(_payload_text(payload))


async def _fake_send_rich(self: Any, chat_id: Any, payload: Any, **kwargs: Any) -> Any:
    """Adapt a legacy send_message double to Kurigram's rich send surface."""
    send = getattr(self, "send_message", None)
    if send is None:
        return None
    forwarded = {
        name: kwargs[name]
        for name in ("reply_markup", "message_thread_id")
        if kwargs.get(name) is not None
    }
    return await send(chat_id, _payload_text(payload), **forwarded)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test that owns the shared PostgreSQL schema.

    CI runs the marked group in one serial step and the rest in parallel.
    The collection hook also catches tests that request the shared
    ``postgres_db`` or ``postgres_url`` fixture without declaring the
    marker themselves, so xdist cannot strand them on a worker that is not
    allowed to own the test schema.
    """
    seen: set[type] = set()
    for item in items:
        fixturenames = getattr(item, "fixturenames", ())
        if "postgres_db" in fixturenames or "postgres_url" in fixturenames:
            item.add_marker(pytest.mark.postgres)
        module = getattr(item, "module", None)
        if module is None:
            continue
        candidates = [getattr(item, "cls", None)]
        candidates.extend(
            obj
            for obj in vars(module).values()
            if isinstance(obj, type) and obj.__module__ == module.__name__
        )
        for cls in candidates:
            if cls is None or cls in seen:
                continue
            seen.add(cls)
            if hasattr(cls, "reply_text") and not hasattr(cls, "reply_rich"):
                cls.reply_rich = _fake_reply_rich  # type: ignore[attr-defined]
            if hasattr(cls, "send_message") and not hasattr(cls, "send_rich_message"):
                cls.send_rich_message = _fake_send_rich  # type: ignore[attr-defined]
            # * Fakes that already expose the Kurigram send surface are
            # * native; only legacy edit doubles need the adapter.
            if hasattr(cls, "edit_message_text") and not hasattr(
                cls, "send_rich_message"
            ):
                _patch_fake_edit(cls)
            if hasattr(cls, "edit_text") and not hasattr(cls, "reply_rich"):
                _patch_fake_edit(cls, "edit_text")


@pytest.fixture(scope="session", autouse=True)
def _production_logging() -> None:
    """Install the production logging setup once, like main() does at startup.

    Modules log through the loguru-backed shim (bridged to stdlib), which
    only reaches caplog and the Telegram error handler after configure()
    runs. Without this, records would fall back to loguru's default
    print-to-stdout facility and tests asserting on log output fail.
    """
    setup_logging()


@pytest.fixture(scope="session", autouse=True)
def _cache_key_namespace() -> None:
    """Move the shared caches into a test-only Redis namespace.

    The shared caches use fixed keys, and the owner cache uses one global
    key. Two workers would therefore read each other's entries when Redis
    is configured, and the tests that pin the cached and the fresh read
    would fail depending on the worker order.

    The namespace is applied in every run, not only under xdist. A serial
    run against a deployment Redis would otherwise write, read, and
    delete keys in the live namespace, where they collide with real cache
    entries of the running bot. The test-only suffix keeps every key the
    suite touches out of the deployment namespace.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    suffix = f"-test-{worker}" if worker else "-test"
    for cache in (
        singletons.effective_role_cache,
        singletons.connected_cache,
        singletons.active_groups_cache,
        singletons.owner_id_cache,
        singletons.user_mention_cache,
        singletons.user_locale_cache,
        singletons.group_locale_cache,
        singletons.community_locale_cache,
    ):
        cache._redis_prefix = f"{cache._redis_prefix}{suffix}"


@pytest.fixture(scope="session", autouse=True)
def _shared_caches_stay_in_memory() -> Iterator[None]:
    """Keep the shared caches on their in-memory layer for the whole suite.

    The Redis half of a cache is eventually consistent: an invalidation
    clears the in-memory entry at once and queues the Redis delete. The
    tests run each case on its own event loop, and a queued delete dies
    with the loop it was queued on, so the stale entry would stay in
    Redis and the next test would read it. The module that exercises
    Redis on purpose restores the configuration.
    """
    memory_only = dataclasses.replace(cfg, redis_url="")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(twolevel, "cfg", memory_only)
        patch.setattr(redis_client_mod, "cfg", memory_only)
        yield


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Return the test database URL and own the schema for the session.

    The test skips when no server is configured, so the committed suite
    never depends on a reachable database.
    """
    url = require_test_database()
    build_test_schema(url)
    try:
        yield url
    finally:
        drop_test_schema(url)


@pytest.fixture
async def postgres_db(postgres_url: str) -> AsyncIterator[str]:
    """Point the shared engine module at the test database."""
    reset_postgres_circuit()
    async with use_test_engine(postgres_url):
        yield postgres_url
