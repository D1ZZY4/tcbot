# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

import logging
from pathlib import Path

from .. import configs

logger = logging.getLogger(__name__)


## Module discovery and filtering

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
