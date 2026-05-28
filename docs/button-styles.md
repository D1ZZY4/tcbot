# Button Style Conventions

Inline keyboard factories are centralized in `tcbot/modules/helper/keyboards.py`, with a few workflow-local pagination keyboards where callback state is private to that workflow.

## General rules

- Use short labels that fit on mobile screens.
- Use title case for action labels: `Approve`, `Reject`, `Cancel`, `Details`.
- Use `« Back` for back navigation and `Next »` / `« Prev` for pagination.
- Put destructive confirmation buttons beside `Cancel` when the decision is binary.
- Use URLs only for external navigation such as proof links and appeal deep links.
- Keep callback data stable; callback handlers depend on regex patterns.

## Common row layouts

### Binary decisions

Use one row with the positive action first and cancel/reject second.

```text
[Confirm] [Cancel]
[Approve] [Reject]
[Connect] [Cancel]
```

Used by demotion, promotion approval, appeal review, and group connection prompts.

### Details and external links

Keep details/back callback buttons separate from URL buttons when possible.

```text
[Details] [Proof]
[Appeal]
```

For a detail view:

```text
[Proof]
[« Back]
```

### Pagination

Use navigation row first, numbered item rows next, then global actions/back row.

```text
[« Prev] [Next »]
[1] [2] [3]
[4] [5] [6]
[Search]
[« Back]
```

## Callback-data naming

Use a namespace prefix and colon-separated fields for structured data.

| Pattern | Meaning |
|---|---|
| `promo_role:{role}:{target_id}` | Promote target to selected role. |
| `promo_role_cancel:{target_id}` | Cancel role selection menu. |
| `demote_confirm:{target_id}` | Confirm demotion. |
| `demote_cancel:{target_id}` | Cancel demotion. |
| `promo_approve:{request_id}` / `promo_reject:{request_id}` | Resolve promotion request. |
| `checkme_detail:{ban_id}` / `checkme_back:{ban_id}` | Toggle `/checkme` detail view. |
| `stats_bans:{page}` | Open active-ban list page. |
| `stats_ban_item:{page}:{index}` | Open a ban detail from a page. |
| `stats_chats:{page}` | Open connected-chat list page. |
| `stats_chat_item:{page}:{index}` | Open a chat detail from a page. |

Some existing appeal and connection callbacks use underscore-only names, such as `appeal_approve_<ban_id>` and `tc_join`. Match the existing namespace for the feature you are editing.

## Label vocabulary

| Use case | Preferred labels |
|---|---|
| Confirmation | `Confirm`, `Cancel` |
| Review | `Approve`, `Reject` |
| Navigation | `« Back`, `Next »`, `« Prev` |
| Detail view | `Details`, `View Proof`, `Proof` |
| Search | `Search`, `New Search`, `Cancel` |
| External navigation | `Open in PM ↗`, `Submit Appeal` |

## Keyboard ownership

Add reusable keyboard factories to `tcbot/modules/helper/keyboards.py`.

Workflow-local keyboards are acceptable when they are tightly coupled to local pagination state, such as stats page buttons. Do not duplicate shared admin, appeal, start-menu, or ban/checking keyboards in command modules.

## Callback handler rules

- Register a `CallbackQueryHandler` with a precise `pattern`.
- Start callback handlers with `await q.answer()` or run it in an `asyncio.gather()` before edits.
- Use `safe_edit()` when repeated callbacks may produce unchanged text.
- Keep callback data small; Telegram callback data has a strict byte limit.
