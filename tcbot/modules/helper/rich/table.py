# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich table formatting. The Bot API supports up to 20 columns per table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tcbot.modules.helper.rich.style import esc

if TYPE_CHECKING:
    from collections.abc import Sequence

_ALIGNMENTS = frozenset({"left", "center", "right"})
_VALIGNMENTS = frozenset({"top", "middle", "bottom"})
# * Bot API rich tables accept at most 20 grid columns, counting colspans.
_MAX_COLUMNS = 20


@dataclass(frozen=True)
class TableCell:
    """One table cell with the layout options Kurigram supports.

    ``header`` marks a header cell; ``colspan`` and ``rowspan`` are emitted only
    when greater than one. ``raw`` keeps trusted inline markup such as a rich
    button verbatim inside one cell, without forcing the whole table raw.
    Unsupported align/valign values are dropped rather than shipped as invalid
    attributes, matching the rich button row helpers.
    """

    text: str
    header: bool = False
    colspan: int = 1
    rowspan: int = 1
    align: str | None = None
    valign: str | None = None
    raw: bool = False

    def __post_init__(self) -> None:
        """Reject span values that cannot form a valid grid cell."""
        if self.colspan < 1 or self.rowspan < 1:
            raise ValueError("Table cell colspan and rowspan must be positive")


def table_cell(
    text: str,
    *,
    header: bool = False,
    colspan: int = 1,
    rowspan: int = 1,
    align: str | None = None,
    valign: str | None = None,
    raw: bool = False,
) -> TableCell:
    """Build a cell with column span, row span, alignment, and trusted markup."""
    return TableCell(
        text=text,
        header=header,
        colspan=colspan,
        rowspan=rowspan,
        align=align,
        valign=valign,
        raw=raw,
    )


def table(
    headers: Sequence[str | TableCell],
    rows: Sequence[Sequence[str | TableCell]],
    *,
    bordered: bool = True,
    striped: bool = False,
    compact: bool = False,
    title: str | None = None,
    raw_cells: bool = False,
) -> str:
    """Render a table.

    ``title`` renders as ``<caption>`` inside ``<table>``, which Kurigram maps
    to ``PageBlockTable.title``. It is the table title, not a section heading;
    use ``rich.formats.heading()`` only for a standalone heading block.

    Cells are escaped by default. Set ``raw_cells`` only when every cell was
    built with trusted inline rich markup helpers.
    """

    def render(value: str | TableCell, default_tag: str) -> str:
        if isinstance(value, TableCell):
            tag = "th" if value.header else default_tag
            attrs = ""
            if value.colspan > 1:
                attrs += f' colspan="{int(value.colspan)}"'
            if value.rowspan > 1:
                attrs += f' rowspan="{int(value.rowspan)}"'
            if value.align in _ALIGNMENTS:
                attrs += f' align="{value.align}"'
            if value.valign in _VALIGNMENTS:
                attrs += f' valign="{value.valign}"'
            content = value.text
        else:
            tag = default_tag
            attrs = ""
            content = value
        keep_markup = raw_cells or (isinstance(value, TableCell) and value.raw)
        text = str(content) if keep_markup else esc(content)
        return f"<{tag}{attrs}>{text}</{tag}>"

    flags = ""
    if bordered:
        flags += " bordered"
    if striped:
        flags += " striped"
    if compact:
        flags += " compact"

    def width(cells: Sequence[str | TableCell]) -> int:
        return sum(cell.colspan if isinstance(cell, TableCell) else 1 for cell in cells)

    # * A malformed table can fail the whole rich message at Telegram. Reject
    # * an over-wide grid here, where the caller can fix it, instead of late.
    if width(headers) > _MAX_COLUMNS or any(width(row) > _MAX_COLUMNS for row in rows):
        raise ValueError(f"A rich table holds at most {_MAX_COLUMNS} columns")

    parts = [f"<table{flags}>"]
    if title:
        parts.append(f"<caption>{esc(title)}</caption>")
    # * A headerless table must not emit an empty <tr></tr> row.
    if headers:
        parts.append("<tr>" + "".join(render(h, "th") for h in headers) + "</tr>")
    parts.extend(
        "<tr>" + "".join(render(value, "td") for value in row) + "</tr>"
        for row in rows
        if row
    )
    parts.append("</table>")
    return "".join(parts)


__all__ = ["table", "table_cell"]
