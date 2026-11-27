# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Module discovery, filtering, and handler collection."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING

from pyrogram.handlers import Handler

from tcbot import cfg
from tcbot.modules.helper.handlers import flatten
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from types import ModuleType

log = get_logger(__name__)


# ──────────────────────── Module Discovery ──────────────────────── #


def _discover_modules() -> list[str]:
    """Return all module names in this directory: .py files and packages.

    Sorted so handler registration order (and the startup log line below)
    is deterministic across filesystems; ``Path`` iteration order is
    OS-dependent and Kurigram resolves overlapping filters in registration order.
    ``helper/`` holds shared code, never handlers, so it stays excluded.
    """
    this_dir = Path(__file__).parent
    names = {
        p.stem for p in this_dir.glob("*.py") if p.is_file() and p.name != "__init__.py"
    }
    for child in this_dir.iterdir():
        if (
            child.is_dir()
            and child.name not in ("helper", "__pycache__")
            and (child / "__init__.py").is_file()
        ):
            names.add(child.name)
    return sorted(names)


def _filter_modules(modules: list[str]) -> list[str]:
    """Apply load / no-load filters from the central configuration."""
    to_load = cfg.modules_load
    no_load = cfg.modules_no_load

    # * Validate both lists against the full discovered set. A denylist name
    # * that is a real module but absent from an allowlist is valid and simply
    # * has no effect; validating after the allowlist would reject it as a typo.
    for label, names in (("MODULES_LOAD", to_load), ("MODULES_NO_LOAD", no_load)):
        invalid = [m for m in names if m not in modules]
        if invalid:
            log.error("%s contains invalid names: %s. Exiting.", label, invalid)
            raise SystemExit(1)

    if to_load:
        # * Filter discovery order instead of following the operator's list:
        # * same-group handlers resolve in registration order, so a config
        # * reorder must not silently change which overlapping filter wins.
        allowed = dict.fromkeys(to_load)
        modules = [m for m in modules if m in allowed]
    if no_load:
        log.info("Not loading modules: %s", no_load)
        modules = [m for m in modules if m not in no_load]

    return modules


# ───────────────────────── Module Registry ──────────────────────── #

ALL_MODULES = _filter_modules(_discover_modules())
log.info("Modules to load: %s", ALL_MODULES)


# ─────────────────────── Handler Collection ─────────────────────── #


def get_handlers() -> list[Handler]:
    """Import all active modules and collect their __handlers__ lists.

    Imports run first so every failure is reported together before the
    fail-fast exit; collection then follows ``ALL_MODULES`` order, which is
    the sorted discovery order filtered by configuration.
    """
    handlers: list[Handler] = []
    mods_found: dict[str, ModuleType] = {}

    failed: list[str] = []
    for mod_name in ALL_MODULES:
        try:
            mods_found[mod_name] = importlib.import_module(f"tcbot.modules.{mod_name}")
        except Exception:
            failed.append(mod_name)
            log.exception("Failed to import tcbot.modules.%s", mod_name)

    if failed:
        raise SystemExit(f"Module import failed for: {', '.join(failed)}")

    for mod_name in ALL_MODULES:
        # * Present by construction: any missing import raised SystemExit above.
        mod_handlers: list[Handler] = getattr(mods_found[mod_name], "__handlers__", [])
        if not mod_handlers:
            log.warning("Module %s registered no handlers", mod_name)
        if mod_handlers:
            expanded = flatten(mod_handlers)
            handlers.extend(expanded)
            log.debug("Loaded %d handler(s) from %s", len(expanded), mod_name)

    return handlers


def handler_group(handler: Handler) -> int:
    """Return the Kurigram group a module handler asked to be registered in.

    Most handlers stay in group 0. A free-text handler that must not shadow an
    active conversation marks itself with ``handler_group`` so the caller can
    place it in a later group, where Kurigram only sees it if no group-0
    handler consumed the ctx.
    """
    return int(getattr(handler, "handler_group", 0))
