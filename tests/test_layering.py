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

# * Hard per-module line budget from the project rules. A module that
# * reaches it is split into a same-named package with focused submodules.
_FILE_BUDGET_LINES = 1000


def _command_modules(root: Path = _TCBOT_ROOT) -> set[str]:
    """Return the import paths of the command modules under ``tcbot/modules``.

    The helper package lives under the same parent but is shared code, so
    it is excluded: only the command handlers count as the layer above.
    """
    modules_dir = root / "modules"
    names: set[str] = set()
    for path in modules_dir.glob("*.py"):
        if path.name != "__init__.py":
            names.add(f"tcbot.modules.{path.stem}")
    for path in modules_dir.iterdir():
        if path.is_dir() and path.name != "helper" and (path / "__init__.py").is_file():
            names.add(f"tcbot.modules.{path.name}")
    return names


def _imported_names(path: Path, root: Path = _TCBOT_ROOT) -> set[str]:
    """Return every absolute module name imported by *path*.

    Relative imports are resolved against the package that holds the file
    and rendered as dotted names, so a sibling import inside
    ``tcbot/utils`` is reported as ``tcbot.utils.<name>`` and a relative
    import that reaches across a layer boundary is reported the same way
    an absolute one is.

    *root* is the package directory the dotted names are relative to; the
    tests point it at a temporary tree so they never write into the
    source tree.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = root
    for part in path.relative_to(root).parts[:-1]:
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
                # * ``base`` is a path; the dotted name is what the layer
                # * rules compare against.
                target = ".".join(base.relative_to(root.parent).parts)
                if node.module:
                    target = f"{target}.{node.module}"
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


def _probe_tree(tmp_path: Path, source: str) -> Path:
    """Return a temporary package root holding *source* as a helper module.

    The probe lives in a temporary tree, never in the source tree, so the
    test cannot race with a parallel run that walks the real files.
    """
    root = tmp_path / "tcbot"
    helper = root / "modules" / "helper"
    helper.mkdir(parents=True)
    (root / "modules" / "bans.py").write_text("", encoding="utf-8")
    probe = helper / "probe.py"
    probe.write_text(source, encoding="utf-8")
    return root


def test_relative_imports_resolve_to_dotted_names(tmp_path: Path) -> None:
    """A relative import must be reported as a dotted module name.

    The layer rules compare dotted names. Resolving a relative import to a
    filesystem path made every relative import look like an unrelated
    absolute one, so a helper could reach into a command module with
    ``from ..bans import ...`` without the rule noticing.
    """
    root = _probe_tree(tmp_path, "from ..bans import cmd_ban\n")
    names = _imported_names(root / "modules" / "helper" / "probe.py", root)
    assert "tcbot.modules.bans" in names
    assert "tcbot.modules.bans.cmd_ban" in names


def test_a_helper_cannot_reach_a_command_module_through_a_relative_import(
    tmp_path: Path,
) -> None:
    """The helper rule must catch the relative form of the same import."""
    root = _probe_tree(tmp_path, "from ..bans import cmd_ban\n")
    probe = root / "modules" / "helper" / "probe.py"
    commands = _command_modules(root)
    offenders = [
        name
        for name in _imported_names(probe, root)
        if name in commands or any(name.startswith(f"{cmd}.") for cmd in commands)
    ]
    assert any("tcbot.modules.bans" in name for name in offenders)


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


def test_a_command_module_does_not_import_another() -> None:
    """Command modules must not reach into each other.

    Two command modules importing each other is a cycle in the making:
    the shared code they both need belongs in the helper layer, where
    both can reach it without depending on each other. It also breaks
    ``MODULES_NO_LOAD``: the filter stops a module from registering its
    handlers, but the import still pulls it in.
    """
    modules_dir = _TCBOT_ROOT / "modules"
    commands = _command_modules()
    offenders: list[str] = []
    for path in sorted(modules_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        self_name = f"tcbot.modules.{path.stem}"
        for name in _imported_names(path):
            if name == self_name:
                continue
            # * A command module imported by name, or one of its members.
            if name in commands or any(name.startswith(f"{cmd}.") for cmd in commands):
                offenders.append(f"{path.name} imports {name}")
    assert not offenders, "command modules must not import each other:" + _report(
        offenders
    )


def test_no_module_exceeds_the_file_budget() -> None:
    """Every module stays inside the documented 1000-line budget.

    The budget is a hard limit in the project rules. Leaving it to
    discipline let two modules reach 90 percent of it, so it is checked
    here instead. A module that grows past the budget is split into a
    same-named package with focused submodules.
    """
    oversized: list[str] = []
    for path in sorted(_TCBOT_ROOT.rglob("*.py")):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > _FILE_BUDGET_LINES:
            oversized.append(
                f"{path.relative_to(_TCBOT_ROOT.parent)}: {line_count} lines"
            )
    assert not oversized, "modules over the file budget:" + _report(oversized)
