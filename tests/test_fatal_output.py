# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Fatal startup banner: fully colored stderr output with stage and traceback."""

from __future__ import annotations

from typing import Any

from tcbot.__main__ import _print_fatal


def test_fatal_banner_colored(capsys: Any) -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        _print_fatal("unit-test", exc)
    err = capsys.readouterr().err
    assert "\033[" in err
    assert "FATAL STARTUP ERROR" in err
    assert "unit-test" in err
    assert "RuntimeError" in err
    assert "Traceback" in err
