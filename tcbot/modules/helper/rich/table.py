# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich table formatting. The Bot API supports up to 20 columns per table."""

from __future__ import annotations

from tcbot.modules.helper.rich.style import esc


def table(
    headers: list[str],
    rows: list[list[str]],
    *,
    bordered: bool = True,
    striped: bool = False,
    compact: bool = False,
    caption: str | None = None,
    raw_cells: bool = False,
) -> str:
    """Render a table.

    Cells are escaped by default. Set ``raw_cells`` only when every cell was
    built with trusted inline rich markup helpers.
    """

    def cell(value: object) -> str:
        return str(value) if raw_cells else esc(value)

    flags = ""
    if bordered:
        flags += " bordered"
    if striped:
        flags += " striped"
    if compact:
        flags += " compact"
    parts = [f"<table{flags}>"]
    if caption:
        parts.append(f"<caption>{esc(caption)}</caption>")
    parts.append("<tr>" + "".join(f"<th>{cell(h)}</th>" for h in headers) + "</tr>")
    parts.extend(
        "<tr>" + "".join(f"<td>{cell(value)}</td>" for value in row) + "</tr>"
        for row in rows
    )
    parts.append("</table>")
    return "".join(parts)


__all__ = ["table"]
