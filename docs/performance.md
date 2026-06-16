# Performance Optimization Guide

For database batch query helpers and indexes, see [`databases/databases.md`](databases/databases.md). For check command which is the main consumer of batch queries, see [`check-detailed.md`](check-detailed.md).

This document outlines the performance optimizations implemented in the tcbot codebase and best practices for maintaining fast response times.

## Overview

The bot is optimized for **zero-delay, instant response** across all operations:

### v4.6.2 Performance Targets (Mandatory)

| Operation | Target |
|---|---|
| Single DB query (indexed) | < 0.1 ms |
| DB batch query (up to 100 docs) | < 0.5 ms |
| Redis read (single key, hiredis) | < 0.03 ms |
| Redis pipeline (multi-key batch) | < 0.08 ms |
| Fan-out to 100 groups | < 30 ms |
| Fan-out to 1,000 groups | < 200 ms |
| Command handler response (p95) | < 5 ms |
| Callback query acknowledgment (`q.answer()`) | < 1 ms |
| APScheduler job execution start | < 5 ms after due time |
| In-memory cache read | < 0.005 ms |
| Identity/role resolution (Redis cached) | < 0.02 ms |
| Startup time to bot ready | < 0.1 s |
| Full federation ban (10 groups, with log) | < 80 ms |
| Cache warm-up full at startup | < 50 ms |
| Identity harvest 1 group (100 members) | < 20 ms |

These targets are achieved via:
- `TwoLevelCache`: in-process L1 (`cachetools.TTLCache`) + Redis L2 (`hiredis` C extension required for sub-0.03 ms reads)
- Batch database queries (no N+1 patterns)
- `asyncio.gather()` for all independent async operations
- Composite MongoDB indexes on all high-frequency query patterns
- `estimated_document_count()` for collection-size metrics
- `q.answer()` parallelised with the first DB/API call in every callback handler
- APScheduler 4.x with `MongoDBDataStore` for persistent job execution
- Bounded fan-out via `tcbot/utils/dispatch.py` (adaptive semaphore, never sequential)

## Key Optimization Strategies

### 1. Batch Database Queries

**Problem:** N+1 query pattern where we fetch user data in a loop.

**Bad (Sequential):**
```python
# Fetches each user individually - N database roundtrips
for user_id in user_ids:
    name = await db.users_cache.get_first_name(user_id)
    # ... use name
```

**Good (Batch):**
```python
# Single database query for all users
name_map = await db.users_cache.get_first_names_batch(user_ids)
for user_id in user_ids:
    name = name_map[user_id]
    # ... use name
```

**Available batch functions:**
- `get_first_names_batch(user_ids)` - Fetch first names for multiple users
- `get_mention_data_batch(user_ids)` - Fetch (first_name, username) tuples
- `get_group_titles(chat_ids)` - Fetch group titles for multiple chats

**Performance gain:** 50-90% reduction in database roundtrips.

---

### 2. Database Projections

**Problem:** Fetching full documents when only few fields are needed.

**Bad (Full Document):**
```python
# Fetches all fields: user_id, username, first_name, last_name, commit_date, last_updated
user = await db.users_cache.get_user(user_id)
name = user.get("first_name")
username = user.get("username")
```

**Good (Projection):**
```python
# Fetches only 2 fields
name, username = await db.users_cache.get_user_mention_data(user_id)
```

**Performance gain:** 40-60% reduction in data transfer.

---

### 3. Parallel Execution

**Problem:** Sequential await statements for independent operations.

**Bad (Sequential):**
```python
# Total time = time1 + time2 + time3
result1 = await operation1()
result2 = await operation2()
result3 = await operation3()
```

**Good (Parallel):**
```python
# Total time = max(time1, time2, time3)
result1, result2, result3 = await asyncio.gather(
    operation1(),
    operation2(),
    operation3(),
)
```

**When to parallelize:**
- Multiple database queries that don't depend on each other
- Database query + Telegram API call
- Multiple Telegram API calls to different chats
- Any independent async operations

**Performance gain:** Eliminates sequential wait times.

---

### 4. Database Indexes

All frequently queried fields have indexes:

```python
# User lookups
col("member_cache").create_index([("user_id", 1)], unique=True)
col("member_cache").create_index([("username", 1)])
col("member_cache").create_index([("first_name", 1)])

# Ban queries
col("bans").create_index([("banned_user_id", 1), ("is_active", 1)])
col("bans").create_index([("is_active", 1), ("timestamp", -1)])

# Warning queries
col("warns").create_index([("user_id", 1), ("chat_id", 1), ("timestamp", -1)])
col("warns").create_index([("user_id", 1), ("timestamp", -1)])
```

**Impact:** 2-5x faster queries on large datasets.

---

### 5. Smart Mention System

**Problem:** `tg://user?id=` mentions only work if user is in the same chat.

**Solution:** Use username-based mentions when available:
```python
def mention(user_id: int, name: str, username: str | None = None) -> str:
    if username:
        # Global mention - works everywhere
        return f'<a href="https://t.me/{username}">{html.escape(name)}</a>'
    else:
        # Fallback - plain text + copyable ID
        return f'{html.escape(name)} <code>{user_id}</code>'
```

**Benefits:**
- Mentions work across all groups when username available
- Clean fallback for users without username
- No performance penalty

---

## Performance Benchmarks

### Pre-v4 Baseline (before architectural optimizations)

These were measured before the batch-query, gather-parallelism, and cache-layer
rewrites introduced in v4. They serve as the reference point for the v4+ targets.

- Stats command: 2-3 seconds with 50 staff members
- Check command: 3-5 seconds with 100 warnings
- Ban list: 1-2 seconds with 50 bans
- Staff roster: 1.5-2 seconds

### v4.6.2 Architecture Targets

The v4.6.2 targets (listed in the table above) are the binding architecture goals.
Achieving them requires the full stack to cooperate:

| Layer | Contribution |
|---|---|
| In-memory L1 (cachetools TTLCache) | Role and identity reads: < 0.005 ms |
| Redis L2 (hiredis C extension) | Distributed reads: < 0.03 ms |
| MongoDB (indexed query, Atlas) | Single doc: < 0.1 ms; batch 100: < 0.5 ms |
| Network to Telegram API | Baseline round-trip adds ~50-200 ms depending on region |

The command handler p95 target of < 5 ms covers the **bot-side** processing time
(cache lookups, DB reads, business logic, response formatting) and does not include
the Telegram network round-trip. End-to-end time as seen by the user includes the
network leg, which is outside the bot's control.

### Button Handlers
- Callback query acknowledgment (`q.answer()`): < 1 ms (bot-side)
- Full callback round-trip (answer + edit): < 5 ms (bot-side processing)

---

## Best Practices

### When Writing New Code

1. **Always use batch queries for lists:**
   ```python
   # Get all user IDs first
   user_ids = [item["user_id"] for item in items]
   # Single batch query
   name_map = await db.users_cache.get_first_names_batch(user_ids)
   # Use the map
   for item in items:
       name = name_map[item["user_id"]]
   ```

2. **Always parallelize independent operations:**
   ```python
   # If operations don't depend on each other, use gather
   user_data, role, ban_status = await asyncio.gather(
       db.users_cache.get_user(user_id),
       db.bans_db.get_active_ban(user_id),
       db.groups_db.get_group(chat_id),
   )
   ```

3. **Use projections when possible:**
   ```python
   # Don't fetch full document if you only need specific fields
   doc = await col("users").find_one(
       {"user_id": user_id},
       {"first_name": 1, "username": 1}  # Only fetch these fields
   )
   ```

4. **Add indexes for new query patterns:**
   ```python
   # If you add a new query that filters by a field, add an index
   await col("new_collection").create_index([("new_field", 1)])
   ```

5. **Avoid loops with await inside:**
   ```python
   # Bad
   for user_id in user_ids:
       await process_user(user_id)
   
   # Good
   await asyncio.gather(*[process_user(uid) for uid in user_ids])
   ```

---

## Common Patterns

### Pattern 1: List View with User Names

```python
async def list_items(items: list[dict]) -> str:
    # Extract all user IDs
    user_ids = [item["user_id"] for item in items]
    
    # Single batch query
    name_map = await db.users_cache.get_first_names_batch(user_ids)
    
    # Build output
    lines = []
    for item in items:
        name = name_map[item["user_id"]]
        lines.append(f"{name}: {item['data']}")
    
    return "\n".join(lines)
```

### Pattern 2: Command Handler with Multiple Queries

```python
async def cmd_example(update, ctx):
    user = update.effective_user
    
    # Parallelize all independent queries
    user_data, role, ban_status = await asyncio.gather(
        db.users_cache.get_user(user.id),
        db.users_cache.get_effective_role(user.id),
        db.bans_db.get_active_ban(user.id),
    )
    
    # Process results...
```

### Pattern 3: Callback Handler with DB + Telegram API

```python
async def on_button_click(update, ctx):
    q = update.callback_query
    
    # Parallelize answer + data fetch
    _, data = await asyncio.gather(
        q.answer(),
        fetch_data_from_db(),
    )
    
    # Edit message with result
    await q.edit_message_text(format_data(data))
```

---

## Monitoring Performance

### Adding Timing Logs (Development Only)

```python
import time

start = time.perf_counter()
result = await slow_operation()
elapsed = time.perf_counter() - start
log.debug(f"Operation took {elapsed:.3f}s")
```

### Identifying Bottlenecks

1. **Check for N+1 patterns:** Look for loops with `await` inside
2. **Check for sequential operations:** Look for multiple `await` statements in sequence
3. **Check for missing projections:** Look for `find_one()` without projection parameter
4. **Check for missing indexes:** Run `.explain()` on slow queries in MongoDB

---

## Performance Checklist

Before merging new code, verify:

- [ ] No N+1 query patterns (use batch queries)
- [ ] Independent operations use `asyncio.gather()`
- [ ] Database queries use projections when possible
- [ ] New query patterns have appropriate indexes
- [ ] No loops with `await` inside (use gather instead)
- [ ] Callback query `q.answer()` responds in < 1 ms
- [ ] Command handlers respond (p95) in < 5 ms
- [ ] Single indexed DB query < 0.1 ms; batch (up to 100 docs) < 0.5 ms
- [ ] Redis single-key read < 0.03 ms (requires hiredis C extension)
- [ ] Identity/role resolution < 0.02 ms (requires Redis L2 cache active)
- [ ] List views paginate efficiently

---

## Related Documentation

- `docs/databases/databases.md` - Database layer and query optimization
- `docs/helper/helper.md` - Helper functions including batch queries
- `CHANGELOG.md` - Performance improvements changelog
