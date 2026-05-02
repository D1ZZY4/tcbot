# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

import importlib
import logging
from pathlib import Path
from typing import Any

from .. import configs

logger = logging.getLogger(__name__)


## ---------------------------------------------------------------------------
## Module discovery and filtering
## ---------------------------------------------------------------------------

def _discover_modules() -> list[str]:
    """Return all .py module names in this directory, excluding __init__.py."""
    this_dir = Path(__file__).parent
    return [
        p.stem
        for p in this_dir.glob("*.py")
        if p.is_file() and p.name != "__init__.py"
    ]


def _filter_modules(modules: list[str]) -> list[str]:
    """
    Apply load / no-load filters from the central configuration.
    - If configs.modules_load is not empty, keep only those and validate.
    - If configs.modules_no_load is not empty, remove those.
    """
    to_load = configs.modules_load
    no_load = configs.modules_no_load

    if to_load:
        invalid = [m for m in to_load if m not in modules]
        if invalid:
            logger.error(
                "MODULES_LOAD contains invalid names: %s. Exiting.", invalid
            )
            raise SystemExit(1)
        modules = [m for m in to_load if m in modules]

    if no_load:
        logger.info("Not loading modules: %s", no_load)
        modules = [m for m in modules if m not in no_load]

    return modules


ALL_MODULES = _filter_modules(_discover_modules())
logger.info("Modules to load: %s", ALL_MODULES)

__all__ = ALL_MODULES + ["ALL_MODULES"]


## ---------------------------------------------------------------------------
## Handler discovery
## ---------------------------------------------------------------------------

## ConversationHandlers and affiliation must be registered first
_PRIORITY_FIRST = ["connecting", "admins", "appealing", "banning", "muting", "kicking", "warnings"]
## Greeting and start last to avoid filter shadowing
_PRIORITY_LAST = ["start", "greeting"]


def get_handlers() -> list[Any]:
    """
    Import all active modules and collect their __handlers__ lists,
    respecting the priority order defined above.
    """
    handlers: list[Any] = []
    mods_found: dict[str, Any] = {}

    for mod_name in ALL_MODULES:
        try:
            mod = importlib.import_module(f"tcbot.modules.{mod_name}")
            mods_found[mod_name] = mod
        except Exception as exc:
            logger.error("Failed to import tcbot.modules.%s: %s", mod_name, exc)

    ordered = (
        [n for n in _PRIORITY_FIRST if n in mods_found]
        + [n for n in mods_found if n not in _PRIORITY_FIRST and n not in _PRIORITY_LAST]
        + [n for n in _PRIORITY_LAST if n in mods_found]
    )

    for mod_name in ordered:
        mod = mods_found[mod_name]
        mod_handlers = getattr(mod, "__handlers__", [])
        if mod_handlers:
            handlers.extend(mod_handlers)
            logger.debug("Loaded %d handler(s) from %s", len(mod_handlers), mod_name)

    return handlers
