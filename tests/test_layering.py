# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Layering contract: the shared layers stay below the domain layers.

The repository is a modular monolith with three layers under the command
handlers:

    tcbot/modules/*.py        command handlers
    tcbot/modules/helper/     domain: roles, targets, keyboards, flows
    tcbot/database/           storage
    tcbot/utils/              shared foundation used by both of the above

The dependency direction is what keeps the tree navigable. It is easy to
break by accident, so the direction is pinned here instead of being left
to tribal knowledge.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from tcbot import error_reporter
from tcbot.utils import logger as logger_mod

_TCBOT_ROOT = Path(__file__).resolve().parent.parent / "tcbot"

# * The utils package is the shared foundation. The database layer and the
# * helper layer both build on it, so it must not depend on either.
_FORBIDDEN_IN_UTILS = ("tcbot.modules", "tcbot.database", "tcbot.error_reporter")


def _command_modules() -> set[str]:
    """Return the import paths of the command modules under ``tcbot/modules``.

    The helper package lives under the same parent but is shared code, so
    it is excluded: only the command handlers count as the layer above.
    """
    modules_dir = _TCBOT_ROOT / "modules"
    names: set[str] = set()
    for path in modules_dir.glob("*.py"):
        if path.name != "__init__.py":
            names.add(f"tcbot.modules.{path.stem}")
    for path in modules_dir.iterdir():
        if path.is_dir() and path.name != "helper" and (path / "__init__.py").is_file():
            names.add(f"tcbot.modules.{path.name}")
    return names


def _imported_names(path: Path) -> set[str]:
    """Return every absolute module name imported by *path*.

    Relative imports are resolved against the package that holds the file,
    so a sibling import inside ``tcbot/utils`` is reported as
    ``tcbot.utils.<name>`` and stays inside the allowed layer.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _TCBOT_ROOT
    for part in path.relative_to(_TCBOT_ROOT).parts[:-1]:
        package = package / part
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package
                for _ in range(node.level - 1):
                    base = base.parent
                target = str(base / (node.module or "")).replace("\\", "/")
                names.add(target)
                names.update(f"{target}.{alias.name}" for alias in node.names)
                continue
            if node.module:
                names.add(node.module)
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _offenders(root: Path, forbidden: tuple[str, ...]) -> list[str]:
    """Return one report line per import that breaks the layer boundary."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        found.extend(
            f"{path.relative_to(_TCBOT_ROOT)} imports {name}"
            for name in _imported_names(path)
            if name.startswith(forbidden)
        )
    return found


def _command_import_offenders(root: Path) -> list[str]:
    """Return the imports that reach from *root* into a command module."""
    commands = _command_modules()
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        found.extend(
            f"{path.relative_to(_TCBOT_ROOT)} imports {name}"
            for name in _imported_names(path)
            if name in commands or any(name.startswith(f"{cmd}.") for cmd in commands)
        )
    return found


def _report(offenders: list[str]) -> str:
    """Render the offender list, capped so the failure stays readable."""
    shown = "\n  ".join(offenders[:10])
    extra = len(offenders) - 10
    tail = f"\n  ... and {extra} more" if extra > 0 else ""
    return f"\n  {shown}{tail}"


def test_utils_stays_below_the_database_and_helper_layers() -> None:
    """The shared foundation must not depend on the layers built on it.

    A ``utils`` module that imported a database helper or a command module
    would turn the foundation into a peer of its own consumers, and the
    import cycle would only show up at runtime. The error reporter lives
    above the utils layer too, so it may not be imported from there
    either; it registers a sink with the logger instead.
    """
    offenders = _offenders(_TCBOT_ROOT / "utils", _FORBIDDEN_IN_UTILS)
    assert not offenders, "utils must not import the domain layers:" + _report(
        offenders
    )


def test_the_error_reporter_registers_its_sink_with_the_logger() -> None:
    """The reporter must reach the logger through the sink, not an import.

    The logger lives in the utils layer, so it cannot import the reporter
    back. The reporter registers a shipping coroutine instead, and that
    registration is what connects an error record to the error channel.
    """

    class _FakeBot:
        async def send_message(self, *a: Any, **k: Any) -> Any:
            return type("M", (), {"message_id": 1})()

    error_reporter.attach(_FakeBot(), -100123, 7)  # type: ignore[arg-type]
    try:
        assert logger_mod._record_sink is not None
    finally:
        logger_mod.set_record_sink(None)


def test_helper_stays_below_the_command_modules() -> None:
    """The shared helper layer must not import a command module back.

    A helper that reached into ``tcbot.modules.bans`` would close a cycle
    between the handler and the code it delegates to.
    """
    offenders = _command_import_offenders(_TCBOT_ROOT / "modules" / "helper")
    assert not offenders, "helper must not import a command module:" + _report(
        offenders
    )


def test_database_stays_below_the_command_modules() -> None:
    """The storage layer must not import a command module back.

    The scheduler injects its enforcement runner from startup for exactly
    this reason: the database package never reaches into a handler.
    """
    offenders = _command_import_offenders(_TCBOT_ROOT / "database")
    assert not offenders, "database must not import a command module:" + _report(
        offenders
    )
