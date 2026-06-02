---
name: Pagination refactor pattern
description: paginate/nav_row/date_or_unknown live in tcbot.utils.pagination; flow files call them directly with _PAGE_SIZE; never define private wrappers in flow files
---

# Pagination helper location

All three shared helpers live in `tcbot.utils.pagination`:

- `paginate(items, page, page_size)` → `(chunk, total_pages, clamped_page)`
- `nav_row(page, total_pages, cb_prefix)` → `list[InlineKeyboardButton]`
- `date_or_unknown(value)` → formatted date string or `"Unknown"`

## Rule

Flow files (`*_flow.py`) must import these directly and call them with their own `_PAGE_SIZE` constant as the third argument to `paginate`. They must NOT define private wrappers (`_paginate`, `_nav_row`, `_date`, etc.).

**Why:** An earlier refactor extracted these into `tcbot.utils.pagination` but left the call sites using the old private names, causing `NameError` at runtime whenever stats or check drill-downs were triggered. The same mistake was present in both `stats_flow.py` and `check_flow.py`.

**How to apply:** Any new `*_flow.py` that needs pagination must start with:
```python
from tcbot.utils.pagination import date_or_unknown, nav_row, paginate
```
and call `paginate(items, page, _PAGE_SIZE)` directly.
