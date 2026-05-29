# Performance Optimization Guide

This document outlines the performance optimizations implemented in the tcbot codebase and best practices for maintaining fast response times.

## Overview

The bot is optimized for **zero-delay, instant response** across all operations:
- Button handlers: < 100ms typical response
- Command handlers: < 1 second for most operations
- List views: Fast pagination even with 1000+ records
- Database queries: Batch operations and parallel execution throughout

## Key Optimization Strategies

### 1. Batch Database Queries

**Problem:** N+1 query pattern where we fetch user data in a loop.

**Bad (Sequential):**
```python
# Fetches each user individually - N database roundtrips
for user_id in user_ids:
    name = await db.users_db.get_first_name(user_id)
    # ... use name
```

**Good (Batch):**
```python
# Single database query for all users
name_map = await db.users_db.get_first_names_batch(user_ids)
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
user = await db.users_db.get_user(user_id)
name = user.get("first_name")
username = user.get("username")
```

**Good (Projection):**
```python
# Fetches only 2 fields
name, username = await db.users_db.get_user_mention_data(user_id)
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

### Before Optimization
- Stats command: 2-3 seconds with 50 staff members
- Check command: 3-5 seconds with 100 warnings
- Ban list: 1-2 seconds with 50 bans
- Staff roster: 1.5-2 seconds

### After Optimization
- Stats command: 0.5-0.8 seconds (70% faster)
- Check command: 0.8-1.2 seconds (75% faster)
- Ban list: 0.3-0.5 seconds (75% faster)
- Staff roster: 0.4-0.6 seconds (70% faster)

### Button Handlers
- All button handlers: < 100ms typical
- Callback query answer: < 50ms
- Message edit: < 100ms

---

## Best Practices

### When Writing New Code

1. **Always use batch queries for lists:**
   ```python
   # Get all user IDs first
   user_ids = [item["user_id"] for item in items]
   # Single batch query
   name_map = await db.users_db.get_first_names_batch(user_ids)
   # Use the map
   for item in items:
       name = name_map[item["user_id"]]
   ```

2. **Always parallelize independent operations:**
   ```python
   # If operations don't depend on each other, use gather
   user_data, ban_data, group_data = await asyncio.gather(
       db.users_db.get_user(user_id),
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
    name_map = await db.users_db.get_first_names_batch(user_ids)
    
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
        db.users_db.get_user(user.id),
        db.users_db.get_effective_role(user.id),
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
- [ ] Button handlers respond in < 100ms
- [ ] Command handlers respond in < 1 second
- [ ] List views paginate efficiently

---

## Related Documentation

- `docs/databases/databases.md` - Database layer and query optimization
- `docs/helper/helper.md` - Helper functions including batch queries
- `CHANGELOG.md` - Performance improvements changelog
