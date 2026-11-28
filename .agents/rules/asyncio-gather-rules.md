# Asyncio Concurrency, Gather, and Fan-Out Rules

This document defines the asynchronous execution, concurrency, structured task management, parallel database access, Telegram fan-out, timeout, cancellation, and background job standards for TCF Bot.

Its primary objectives are to:

- Maintain a responsive, non-blocking event loop.
- Enforce bounded concurrency and predictable resource consumption.
- Prefer structured concurrency over unmanaged task execution.
- Make failure propagation, partial failures, and cancellation explicit.
- Prevent database session conflicts and connection pool exhaustion.
- Respect Telegram API limits and federation-wide operational constraints.
- Provide consistent observability, graceful shutdown, and reliable recovery.

These rules apply to asynchronous handlers, application services, domain pipelines, database helpers, Telegram operations, scheduled jobs, and background workers.

**Related project documentation:**

- Handler authorization and permission boundaries: [`security-rules.md`](security-rules.md).
- Python conventions, typing, and module boundaries: [`code-style.md`](code-style.md).
- CI/CD and validation requirements: [`docs/operations/ci-cd.md`](../../docs/operations/ci-cd.md).

---

## 1. Core Async Principles

All asynchronous application code must follow these principles.

### 1.1 Event Loop Safety

The application owns its asyncio event loop. Application components must cooperate with that lifecycle rather than creating independent event loops.

Rules:

- Keep asynchronous execution asynchronous from entrypoint to completion.
- Always `await` coroutine calls unless they are deliberately scheduled and supervised.
- Never call `asyncio.run()` inside handlers, database helpers, services, pipelines, or scheduled jobs.
- Never block the event loop with synchronous I/O, long-running CPU operations, or blocking waits.
- Do not create independent event loops to work around an existing asynchronous integration.
- Use the application's established lifecycle for startup, shutdown, and resource management.

### 1.2 Concurrency Is Not Parallel CPU Execution

`asyncio` provides cooperative concurrency. It does not automatically execute CPU-bound Python code in parallel.

Use concurrency for independent operations involving asynchronous I/O, such as:

- Telegram API requests.
- Asynchronous database queries.
- Asynchronous network requests.
- Independent external service lookups.
- Concurrent domain operations with explicitly defined failure semantics.

Use appropriate worker infrastructure for CPU-bound operations.

### 1.3 Resource Ownership

Every asynchronous operation must have a clear owner responsible for its lifecycle.

The owner must define:

- When the operation starts.
- How many concurrent operations are allowed.
- How failures are propagated or isolated.
- What happens when the caller is cancelled.
- How timeouts are enforced.
- How resources are released.
- How the operation is observed and stopped.

Unmanaged fire-and-forget execution is prohibited.

---

## 2. Pattern Selection

Choose the concurrency primitive based on the required execution and failure semantics, not simply because several operations can run simultaneously.

| Situation | Preferred pattern |
|---|---|
| One independent asynchronous operation | Direct `await` |
| A few independent operations that must share one lifecycle | `asyncio.TaskGroup` |
| Independent operations requiring aggregate ordered results and intentionally independent sibling lifetimes | `asyncio.gather()` |
| Large or bounded database workloads | `gather_bounded()` |
| Federation-wide Telegram operations | `tcbot.utils.dispatch.fan_out()` |
| User-driven multi-step workflows | Domain-specific asynchronous pipeline |
| Sequential operations with dependencies | Sequential `await` |
| Long-running application-owned workers | Supervised background task lifecycle |
| Scheduled expiration, cleanup, or maintenance | APScheduler through `tcbot/database/scheduler/` |
| Blocking I/O | `asyncio.to_thread()` when appropriate |
| CPU-intensive processing | Managed process pool or dedicated worker |

**Selection requirements:**

- Prefer structured concurrency when tasks belong to the same operation and should terminate together.
- Use `gather()` only when its exception and cancellation behavior is intentional.
- Use bounded execution for potentially large workloads.
- Preserve sequential execution whenever ordering, transaction integrity, or dependencies require it.
- Never introduce concurrency merely to reduce the apparent number of `await` statements.

---

## 3. Asynchronous Handler Design

Handlers are lightweight application entrypoints and orchestration boundaries.

They should validate the incoming request, obtain the required context, delegate domain operations, and construct the appropriate response.

Persistence belongs in `tcbot/database/` domain helpers. Shared formatting belongs in reusable helpers. Multi-step domain workflows belong in appropriately named modules under `tcbot/modules/helper/pipelines/`.

Rules:

- Keep handlers small, typed, and asynchronous.
- Separate request validation, authorization, domain execution, persistence, and presentation.
- Follow `security-rules.md` for all authorization and permission requirements.
- Guard optional update, message, user, and chat context before accessing it.
- Use the actual API exposed by the pinned Kurigram integration and project context types.
- Do not assume PTB-specific accessors such as `effective_message`, `effective_user`, or `effective_chat` unless they are explicitly implemented by the current project abstraction.
- Do not introduce compatibility shims solely to preserve obsolete framework conventions.
- Avoid direct SQL, database session management, and duplicated persistence logic in handlers.
- Await all Telegram API and database operations.
- Do not create unmanaged background work from a handler.
- Do not catch and suppress unexpected failures merely to keep the handler returning successfully.

A handler may orchestrate multiple domain helpers, but it must not become an alternative implementation of their business logic.

---

## 4. Structured Concurrency with `asyncio.TaskGroup`

`asyncio.TaskGroup` is the preferred primitive for concurrent operations that belong to the same logical execution scope.

It is available in Python 3.11 and later and is part of the standard asyncio API supported by the project's Python 3.14+ baseline.

### 4.1 Preferred Usage

Use `TaskGroup` when:

- Multiple independent operations must complete before continuing.
- Their lifecycle belongs to the current operation.
- A failure should cancel the remaining sibling operations.
- The caller must not leave unfinished child tasks behind.
- Resource cleanup and exception propagation must be predictable.

Example:

```python
async def resolve_moderation_context(
    executor_id: int,
    update: Update,
    args: list[str],
    ctx: Ctx,
) -> tuple[Role, Target]:
    async with asyncio.TaskGroup() as group:
        role_task = group.create_task(
            db.users_roles.get_effective_role(executor_id),
            name="resolve-executor-role",
        )

        target_task = group.create_task(
            extraction.extract_target(update, args, ctx.bot),
            name="resolve-moderation-target",
        )

    return role_task.result(), target_task.result()
```

The example is illustrative and must use the exact project types and Kurigram integration interfaces.

### 4.2 Failure Semantics

When a task inside a `TaskGroup` raises an exception other than `CancelledError`:

- The remaining unfinished sibling tasks are cancelled.
- The task group waits for its child tasks to finish.
- Failures are propagated through an exception group when appropriate.
- The task group does not exit while its managed children are still running.

Rules:

- Do not catch and suppress exceptions inside child tasks unless partial success is explicitly part of the contract.
- Handle `ExceptionGroup` at an appropriate application or domain boundary.
- Use `except*` when selective handling of grouped exception types is necessary.
- Avoid converting unexpected failures into successful-looking return values.
- Keep child task execution independent whenever practical.

### 4.3 Task Naming

Name important concurrent tasks when doing so improves diagnostics.

Task names should describe the operation rather than contain user-controlled content or sensitive information.

Examples:

```python
name="load-user-profile"
name="resolve-target-chat"
name="refresh-group-metadata"
```

Avoid excessively detailed names that create high-cardinality observability data.

---

## 5. Parallel Work with `asyncio.gather()`

`asyncio.gather()` remains supported and useful. However, its behavior must not be confused with structured concurrency.

### 5.1 Basic Usage

Use `gather()` for a small collection of independent awaitables when aggregate ordered results are required and its failure behavior is acceptable.

```python
role, settings = await asyncio.gather(
    db.users_roles.get_effective_role(executor_id),
    db.users_settings.get_user_settings(executor_id),
)
```

Rules:

- Only execute independent operations concurrently.
- Preserve the original input order when consuming aggregated results.
- Avoid sharing mutable state between concurrent operations.
- Ensure every operation has an appropriate timeout and resource boundary.
- Do not parallelize dependent operations.
- Prefer `TaskGroup` when sibling operations should share a single failure and cancellation lifecycle.

### 5.2 Exception Behavior

By default, `asyncio.gather()` propagates the first exception raised by its awaitables.

An important distinction:

**Other submitted awaitables are not automatically cancelled when one awaitable raises an exception.**

They may continue executing after the caller has already received the exception.

This can cause:

- Operations continuing after the handler exits.
- Unexpected side effects after a failure.
- Unobserved task exceptions.
- Resources remaining occupied longer than expected.
- Confusing application shutdown behavior.

Therefore:

- Never assume `gather()` provides TaskGroup-style sibling cancellation.
- Do not use it for coordinated side-effecting operations when unfinished siblings must stop after a failure.
- Do not assume calling `gather.cancel()` after it has already propagated an exception will cancel the remaining operations.
- Prefer `TaskGroup` whenever a shared lifecycle is required.

### 5.3 `return_exceptions=True`

Only use `return_exceptions=True` when partial results are an intentional part of the operation's contract.

Every returned element must be inspected before it is treated as a successful result.

Rules:

- Distinguish returned values from returned exceptions.
- Handle only explicitly anticipated error categories.
- Preserve unexpected exceptions for the appropriate reporting boundary.
- Never silently replace failed results with success defaults.
- Never treat cancellation as an ordinary operational failure.
- Do not use exception objects as if they were valid domain results.

Remember that cancellation-related exceptions require special treatment. `asyncio.CancelledError` is derived from `BaseException`, not ordinary `Exception`.

For ordinary structured work, prefer `TaskGroup` instead of using `return_exceptions=True` as a workaround for unclear failure handling.

---

## 6. Bounded Concurrency and Fan-Out

Concurrency must be bounded according to the capacity and behavior of the downstream system.

A workload is not considered bounded merely because it contains a semaphore.

### 6.1 Bounded Execution Requirements

Rules:

- Never create an unrestricted number of tasks for large group, user, or record collections.
- Use `gather_bounded()` for project-supported bounded database bursts.
- Use `fan_out()` for federation-wide Telegram operations.
- Use a fixed-size worker pool or bounded queue for large dynamic workloads.
- Prefer incremental consumption over eagerly creating thousands of coroutine objects.
- Keep concurrency limits configurable and aligned with actual downstream capacity.
- Avoid creating multiple independent concurrency controls that collectively exceed the intended process-wide limit.

A semaphore limits the number of operations inside its protected section. It does not automatically limit the number of tasks already created.

Additionally, a semaphore created separately for each handler invocation does not enforce a process-wide concurrency limit.

Use the project's shared dispatcher or centralized resource controls when a global limit is required.

### 6.2 Database Concurrency

Database concurrency must respect:

- Connection pool capacity.
- Maximum database connections.
- Transaction lifetime.
- Query execution cost.
- Database server capacity.
- Circuit breaker and timeout policies.

Never create more concurrent database work than the configured database infrastructure can reasonably sustain.

Avoid N+1 query patterns disguised as parallel execution. Prefer an appropriately designed batch query when several records can be retrieved together.

---

## 7. Multi-Group Telegram Fan-Out

Federation-wide Telegram actions must use the project's centralized dispatch implementation:

`tcbot.utils.dispatch.fan_out()`

Do not replace its project-level guarantees with raw `asyncio.gather()`.

### 7.1 Standard Usage

```python
from tcbot.utils.dispatch import count_transient_errors, fan_out

active_groups = await db.groups_db.active_groups()

results = await fan_out(
    [
        ctx.bot.ban_chat_member(group["chat_id"], target_id)
        for group in active_groups
    ]
)

failed = count_transient_errors(results)
```

This example assumes the existing dispatcher contract and must remain aligned with its actual implementation.

### 7.2 Required Dispatcher Guarantees

`fan_out()` must provide the following guarantees:

- Bounded concurrent Telegram operations.
- Stable result ordering corresponding to the input ordering.
- Per-operation failure isolation.
- No single ordinary group failure aborting the remaining federation operations.
- Explicit handling of expected and unexpected failures.
- Cancellation propagation when the calling operation or application is cancelled.
- No accidental swallowing of application-level cancellation.
- Consistent integration with Telegram rate limiting, timeout, and circuit breaker policies.

The helper must not turn unexpected infrastructure errors into indistinguishable successful results.

### 7.3 Error Classification

Differentiate operational outcomes.

Examples include:

| Outcome | Treatment |
|---|---|
| Successful Telegram operation | Success |
| Target already in the desired state | Expected no-op when applicable |
| Missing administrator permissions | Permanent group-specific failure |
| Invalid target or group identifier | Validation or permanent failure |
| Telegram rate limiting | Respect the server-provided wait policy |
| Temporary network failure | Retry only when safe and eligible |
| Telegram service failure | Classify according to retry policy |
| Operation timeout | Treat the outcome as potentially uncertain |
| Application cancellation | Propagate cancellation |

Use `count_transient_errors()` for its defined transient-error metric.

Do not interpret that metric as the total number of failed groups.

### 7.4 Reporting and Auditing

Federation-wide operations must preserve operational visibility.

Where applicable, record:

- Total targeted groups.
- Successfully completed operations.
- Expected no-op outcomes.
- Permanent failures.
- Transient failures.
- Timed-out or uncertain outcomes.
- Retry attempts.
- Operation duration.

Provide partial-failure summaries to staff when the outcome affects moderation or federation management.

Important moderation operations must follow the project's audit requirements.

### 7.5 Rate Limiting and Retry Policies

Telegram rate limits must be respected across concurrent operations.

Rules:

- Use the existing Telegram-aware dispatch and rate-limiting infrastructure.
- Respect server-provided retry delays.
- Never implement aggressive retry loops.
- Retry only explicitly classified transient failures.
- Use bounded retries and an overall operation deadline.
- Use exponential backoff with jitter where application-level retry is required.
- Do not retry permission, validation, or other permanent failures.
- Do not retry a side-effecting request merely because its response timed out. The remote operation may already have succeeded.
- Require idempotency or state verification before repeating operations with uncertain outcomes.

Avoid duplicating retry behavior already implemented by Kurigram or the project's dispatch layer.

---

## 8. Timeouts and Deadlines

All potentially unbounded external operations must have an explicit timeout or deadline policy.

Python's `asyncio.timeout()` and `asyncio.timeout_at()` are preferred for scoped asynchronous deadlines.

### 8.1 Timeout Selection

Use different timeout budgets for different operation categories.

Examples:

- External Telegram lookups.
- Database operations.
- External HTTP requests.
- Domain workflows.
- Multi-group moderation operations.
- Background processing.

Rules:

- Use the existing `cfg` configuration system.
- Use dedicated settings with names that describe their actual purpose.
- Do not hardcode timeout literals in application logic.
- Do not reuse unrelated settings merely because they contain duration values.
- A debounce duration is not automatically an operation timeout.
- Use the database's existing `db_call()` timeout instead of adding unnecessary duplicate timeout layers.
- Prefer native client-level connection and request timeouts where supported.
- Define an overall workflow deadline when multiple operations contribute to a single user-facing operation.

### 8.2 Scoped Timeout with `asyncio.timeout()`

Example:

```python
async def fetch_external_user(
    user_id: int,
    *,
    timeout_seconds: float,
) -> dict[str, object] | None:
    try:
        async with asyncio.timeout(timeout_seconds):
            return await external_lookup(user_id)

    except TimeoutError:
        log.warning(
            "External user lookup timed out for user %s",
            user_id,
        )
        return None
```

Returning `None` is acceptable only when the lookup is optional and the caller can safely continue without its result.

Mandatory operations should propagate a meaningful failure rather than silently degrade.

### 8.3 Absolute Deadlines

Use `asyncio.timeout_at()` when several operations must share one overall time budget.

This prevents each nested operation from receiving a fresh full timeout and accidentally extending the total workflow indefinitely.

Use the event loop's monotonic clock for deadline calculations rather than wall-clock timestamps.

### 8.4 `asyncio.wait_for()`

`asyncio.wait_for()` remains valid, but it should not be applied mechanically to every external call.

Use it when a specific awaitable needs an individual timeout wrapper or its cancellation behavior is explicitly desired.

Remember:

- A timeout cancels the awaited operation.
- The operation may perform asynchronous cleanup before cancellation finishes.
- The total wait can exceed the configured timeout while cancellation cleanup completes.
- Nested timeouts require deliberate ownership and exception handling.

Do not combine multiple overlapping timeout mechanisms without a documented reason.

---

## 9. Cancellation and Shutdown Safety

Cancellation is a normal part of asynchronous application lifecycle management.

It occurs during:

- Handler cancellation.
- Application shutdown.
- Worker termination.
- Scheduler shutdown.
- Timeout enforcement.
- Structured task group failure.
- Parent task cancellation.

Cancellation must never be treated as an ordinary successful completion.

### 9.1 Required Cancellation Behavior

Rules:

- Preserve `asyncio.CancelledError`.
- Never swallow cancellation with broad exception handlers.
- Use `try/finally` for resource cleanup.
- If catching `CancelledError` explicitly, perform necessary cleanup and re-raise it.
- Do not return a successful-looking default after cancellation.
- Do not use `uncancel()` as a routine workaround.
- Do not shield routine application operations from cancellation.
- Keep cleanup bounded and avoid delaying shutdown unnecessarily.

Example:

```python
async def worker() -> None:
    try:
        await do_work()

    except asyncio.CancelledError:
        log.debug("Worker cancellation requested")
        await cleanup()
        raise
```

Prefer `finally` when cleanup does not require explicit cancellation-specific branching.

Cleanup failures must also remain observable.

### 9.2 `asyncio.shield()`

`asyncio.shield()` is not a general-purpose method for preventing task cancellation.

Use it only when a narrowly defined operation genuinely needs protection from caller cancellation.

If shielding is necessary:

- Retain a strong reference to the protected task.
- Supervise its completion.
- Observe its exceptions.
- Define when it will be cancelled.
- Ensure application shutdown can still manage it.

Never use shielding to create unmanaged background tasks.

### 9.3 Graceful Shutdown

Application shutdown must:

1. Stop accepting new background work.
2. Stop or pause scheduled task production where appropriate.
3. Cancel application-owned workers that should not continue.
4. Await their completion.
5. Release database and Telegram resources.
6. Flush required audit and operational records within a bounded shutdown budget.
7. Preserve cancellation and report cleanup failures.

Do not terminate while silently abandoning important application-owned operations.

---

## 10. Background Tasks and Supervision

Long-running background tasks must have an explicit application owner.

Preferred ownership mechanisms:

- `asyncio.TaskGroup` for bounded structured lifetimes.
- The application's established worker lifecycle.
- A dedicated task supervisor for long-lived application services.

Rules:

- Prefer `TaskGroup.create_task()` over unmanaged `asyncio.create_task()`.
- Keep a strong reference to every deliberately detached task.
- Observe every task's completion and exception.
- Give important tasks descriptive names.
- Provide cancellation and graceful shutdown mechanisms.
- Prevent duplicate worker startup.
- Do not launch an unlimited number of workers.
- Do not create tasks inside loops without a defined concurrency budget.
- Never assume that a task remains managed simply because it was created with `asyncio.create_task()`.

Fire-and-forget execution is prohibited unless the application explicitly owns and supervises that task.

---

## 11. Scheduled Jobs and APScheduler

Scheduled operations are managed by the application through:

- APScheduler 3.11.3.
- `AsyncIOScheduler`.
- `SQLAlchemyJobStore`.
- `tcbot/database/scheduler/`.

Scheduled jobs belong to the application lifecycle, not to individual Telegram handlers.

### 11.1 Job Execution

Rules:

- Use native asynchronous job functions for asynchronous work.
- Do not block the scheduler's event loop.
- Keep scheduled functions focused on one domain operation.
- Re-load the latest database state when a job executes.
- Do not trust previously captured application state.
- Keep scheduled execution independent of the lifetime of the handler that originally scheduled it.

`AsyncIOScheduler` supports native coroutine jobs. Synchronous job functions are executed through the configured executor and must not contain unbounded blocking work.

### 11.2 Job Persistence

Persistent job data must remain serializable and stable across application restarts.

Pass:

- Primitive identifiers.
- Small serializable values.
- Explicitly defined job parameters.

Do not pass:

- Telegram bot instances.
- Database sessions.
- Live connections.
- Handler contexts.
- Request objects.
- Locks, semaphores, or task objects.
- Large in-memory application objects.
- Unserializable closures or dynamically created callables.

Use stable, importable job functions and reload all necessary dependencies inside the job.

### 11.3 Reliability and Idempotency

Every scheduled job must be designed for repeated execution.

Rules:

- Make operations idempotent whenever practical.
- Verify that the target record still exists.
- Check current state before applying changes.
- Handle records already processed or expired.
- Prevent duplicate scheduling where appropriate.
- Use stable job identifiers.
- Configure `replace_existing`, `max_instances`, `coalesce`, and `misfire_grace_time` according to the intended execution contract.
- Log unexpected exceptions with relevant operation identifiers.
- Never assume that a scheduled job executes exactly once.

A job may execute after its original business context has changed.

### 11.4 Scheduler Lifecycle

Rules:

- Start the scheduler once through the application lifecycle.
- Do not start schedulers from module import side effects.
- Avoid duplicate scheduler initialization.
- Stop the scheduler through controlled application shutdown.
- Keep persistent job-store ownership explicit.
- Do not assume a persistent job store provides distributed locking or multi-process scheduler coordination.
- Ensure the deployment topology has a clear scheduler owner.

---

## 12. Asynchronous Database Access

Database operations must use the established asynchronous database abstraction.

Domain-focused database helpers belong in `tcbot/database/`.

They use SQLAlchemy statements through the asynchronous engine's `engine.db_call()` boundary.

That boundary provides the project's database execution policies, including circuit breaker and call timeout handling.

### 12.1 Database Helper Responsibilities

Rules:

- Keep helpers asynchronous and properly typed.
- Keep persistence logic out of Telegram handlers.
- Follow the ownership and module boundaries defined in `code-style.md`.
- Use SQLAlchemy statements rather than introducing separate raw database access paths.
- Always await database calls.
- Return plain domain data, mappings, typed structures, or DTOs where practical.
- Avoid exposing live sessions, cursors, or database implementation details to handlers.
- Keep database transactions inside the helper that owns the operation.
- Ensure the established circuit breaker and timeout policies are consistently applied.

### 12.2 `AsyncSession` Concurrency Safety

A SQLAlchemy `AsyncSession` represents mutable transaction state.

It is not safe to share a single `AsyncSession` across multiple concurrently executing tasks.

This is a strict rule.

When using:

- `asyncio.TaskGroup`
- `asyncio.gather()`
- `gather_bounded()`
- Other concurrent database execution patterns

Each independently executing database task must receive its own properly scoped `AsyncSession`.

Do not concurrently execute multiple operations against one shared session.

The session lifecycle must remain within the database helper or explicitly defined unit of work that owns it.

### 12.3 Transaction Integrity

Do not parallelize operations that belong to one atomic transaction.

Rules:

- Keep dependent database writes sequential within their transaction.
- Put multi-step atomic changes in one appropriately scoped database helper.
- Avoid distributing one transaction across independently executing tasks.
- Do not use `gather()` to execute writes that must succeed or fail as one atomic unit.
- Never reuse one transaction session across concurrent child tasks.
- Treat transaction rollback and session cleanup as mandatory failure-handling behavior.

### 12.4 Query Efficiency

Prefer efficient database access over increasing concurrency to compensate for inefficient queries.

Rules:

- Use column projection when full model rows are unnecessary.
- Batch related lookups when practical.
- Avoid N+1 query patterns.
- Pre-resolve per-item data for paginated views before formatting.
- Avoid repeating identical queries inside loops.
- Use suitable SQLAlchemy loading strategies.
- Return plain data before leaving the database helper when ORM session lifetime should end.
- Avoid implicit lazy-loading I/O in asynchronous code.

When adding index-sensitive queries:

- Add the appropriate index definition under `tcbot/database/base/`.
- Create and ship the corresponding Alembic revision.
- Validate the query and migration through the project's database validation process.

### 12.5 Database Concurrency Limits

Bound database bursts according to the actual SQLAlchemy connection pool and database capacity.

Do not treat a large number of concurrent queries as inherently faster.

A burst must not cause:

- Connection pool exhaustion.
- Excessive connection acquisition waiting.
- Increased database contention.
- Unnecessary lock contention.
- Excessive memory consumption.
- Cascading timeout failures.

Use `gather_bounded()` for supported independent database workloads.

The helper's concurrency limit must be coordinated with the configured database pool, not chosen arbitrarily.

### 12.6 Retry Safety

Database timeouts and connection failures require careful treatment.

A timed-out write may have reached the database even when the caller did not receive confirmation.

Therefore:

- Never blindly retry uncertain writes.
- Prefer idempotent database operations.
- Use unique constraints or explicit idempotency mechanisms where appropriate.
- Verify resulting state before retrying an operation with an uncertain outcome.
- Do not bypass the central database circuit breaker with independently implemented retries.

---

## 13. Blocking Operations and CPU-Intensive Work

Blocking operations must not execute directly inside the event loop.

### 13.1 Prohibited Operations

Avoid:

- `time.sleep()`; use `await asyncio.sleep()`.
- Synchronous network clients inside asynchronous execution.
- Synchronous database access outside approved database boundaries.
- Long-running CPU loops.
- Large image processing or compression workloads.
- Expensive synchronous file operations.
- Raw blocking subprocess execution from handlers.
- Blocking work inside lightweight Flask keep-alive routes.
- Unbounded synchronous work in scheduled jobs.

### 13.2 Blocking I/O

Use `asyncio.to_thread()` when unavoidable blocking I/O must be isolated.

Example:

```python
result = await asyncio.to_thread(
    sync_file_operation,
    argument,
)
```

Requirements:

- Use it sparingly.
- Ensure the underlying operation is safe to execute in a worker thread.
- Avoid overwhelming the default executor.
- Use dedicated bounded execution infrastructure for substantial workloads.
- Do not assume cancelling the awaiting coroutine terminates the underlying synchronous function.
- Ensure resource cleanup and error handling remain observable.

### 13.3 CPU-Bound Work

`asyncio.to_thread()` is not automatically a solution for CPU-bound pure-Python workloads.

For computationally expensive operations, prefer:

- A managed process pool.
- A dedicated worker process.
- An existing application job execution infrastructure.

Consider thread execution only when the workload's underlying implementation releases the GIL or the runtime demonstrably supports the intended parallel execution model.

Never introduce a process pool or executor without defining its lifecycle, worker count, and resource budget.

### 13.4 Subprocesses

When subprocess execution is genuinely necessary, prefer asyncio-compatible subprocess APIs such as `asyncio.create_subprocess_exec()`.

Rules:

- Avoid shell execution when argument-based execution is sufficient.
- Validate inputs.
- Apply operation timeouts.
- Manage stdout and stderr consumption.
- Terminate and reap child processes when cancellation or timeout occurs.
- Do not leave orphaned processes behind.

---

## 14. Telegram Callback Queries

Callback queries must be acknowledged promptly.

A callback query should be answered before lengthy database operations, network requests, or visible response editing.

Example:

```python
query = update.callback_query

if query is None:
    return

await query.answer()

await safe_edit_cb(
    query,
    "Processing complete.",
)
```

Rules:

- Validate that the callback query exists.
- Call the appropriate Kurigram callback-answer method immediately.
- Do not perform unnecessary database or Telegram operations before acknowledgement.
- Avoid answering the same callback multiple times unintentionally.
- Keep visible edits and subsequent operations appropriately supervised.
- Handle expired or invalid callbacks according to the project's Telegram error-handling conventions.

The example assumes the current Kurigram integration exposes the illustrated method names.

---

## 15. Error Handling and Observability

Asynchronous failures must be visible, classifiable, and actionable.

### 15.1 Error Handling

Rules:

- Catch exceptions at the narrowest boundary that can handle them correctly.
- Do not use broad exception handling to conceal programming errors.
- Preserve exception context.
- Distinguish expected operational failures from unexpected application failures.
- Propagate cancellation.
- Avoid converting infrastructure failures into successful-looking values.
- Use project-standard logging and error classification.

### 15.2 Structured Logging

Include useful operational context where available:

- Operation name.
- Handler or pipeline identifier.
- Telegram chat or group identifier.
- Relevant domain record identifier.
- Task or job identifier.
- Attempt number.
- Execution duration.
- Error classification.

Never log:

- Bot tokens.
- API credentials.
- Authentication secrets.
- Sensitive user data.
- Unnecessary message contents.
- Unredacted database credentials.

### 15.3 Performance Monitoring

Important asynchronous workflows should expose useful measurements.

Examples:

- Operation duration.
- Concurrent operations.
- Timeout frequency.
- Retry frequency.
- Database pool utilization.
- Fan-out success and failure counts.
- Scheduler job execution duration.
- Worker failures.
- Circuit breaker state transitions.

Avoid high-cardinality metric labels containing user-controlled identifiers.

Observability must help diagnose operational problems without introducing excessive overhead.

---

## 16. Testing Asynchronous Execution

Concurrency behavior must be validated, not inferred from code appearance.

When developing or modifying asynchronous execution, test the relevant behaviors.

### 16.1 Required Test Scenarios

Where applicable, cover:

- Successful execution of independent operations.
- Correct result ordering.
- TaskGroup cancellation following sibling failure.
- `gather()` behavior when one operation fails.
- Correct handling of `return_exceptions=True`.
- Bounded maximum concurrency.
- Partial failure isolation in `fan_out()`.
- Correct classification of Telegram failures.
- Timeout enforcement.
- Cancellation propagation.
- Cleanup after cancellation.
- Database session isolation between concurrent tasks.
- Database transaction rollback behavior.
- Retry limits and idempotency.
- Background task exception supervision.
- Scheduled job idempotency.
- Graceful application shutdown.

### 16.2 Concurrency Assertions

Do not validate bounded concurrency merely by checking that a semaphore exists.

Test the actual maximum number of simultaneous operations.

Verify that:

- Active operations never exceed the configured limit.
- Failed operations do not silently increase concurrency.
- Cancellation does not leave unfinished tasks behind.
- Results correspond to the intended input records.
- Expected failures do not prevent unrelated operations from completing.

Prefer deterministic synchronization primitives such as `asyncio.Event` when testing concurrency behavior instead of fragile timing assumptions.

### 16.3 Regression Protection

When changing a shared dispatcher, database execution wrapper, timeout mechanism, or background task supervisor, validate existing callers and their execution contracts.

A change to concurrency infrastructure can affect many unrelated handlers and pipelines.

---

## 17. Implementation and Review Checklist

Before completing asynchronous development, verify every applicable item.

### Handler and Execution Lifecycle

- [ ] Handler functions remain small and asynchronous.
- [ ] Optional context values are validated.
- [ ] Kurigram API usage matches the pinned integration.
- [ ] No unnecessary framework compatibility layer was introduced.
- [ ] Every coroutine is awaited or deliberately scheduled and supervised.
- [ ] No nested `asyncio.run()` calls exist.
- [ ] No unmanaged fire-and-forget tasks were introduced.

### Concurrency

- [ ] Independent work is genuinely independent.
- [ ] `TaskGroup` is preferred for shared structured lifecycles.
- [ ] `gather()` semantics are explicitly understood.
- [ ] No task is assumed to be cancelled merely because `gather()` propagated an exception.
- [ ] `return_exceptions=True` results are inspected correctly.
- [ ] Large workloads use bounded execution.
- [ ] Semaphore usage does not hide unbounded task creation.
- [ ] Process-wide concurrency requirements are enforced centrally.

### Telegram Operations

- [ ] Federation-wide actions use `fan_out()`.
- [ ] Telegram rate limits are respected.
- [ ] Retry policies are bounded and safe.
- [ ] Partial failures are classified correctly.
- [ ] Operator-facing outcomes are reported where necessary.
- [ ] Cancellation propagates through dispatch operations.

### Timeouts and Cancellation

- [ ] External operations have appropriate timeouts.
- [ ] Database calls use the established `db_call()` timeout.
- [ ] Overall workflows have appropriate deadlines.
- [ ] No unnecessary nested timeout mechanisms exist.
- [ ] `CancelledError` is never silently swallowed.
- [ ] Resource cleanup remains reliable.
- [ ] No unmanaged shielded tasks exist.

### Database

- [ ] Database access uses the approved asynchronous helpers.
- [ ] Every concurrent task has an independently scoped `AsyncSession`.
- [ ] Transactions preserve atomicity.
- [ ] No N+1 query pattern was introduced.
- [ ] Database concurrency respects connection pool capacity.
- [ ] Required indexes and Alembic revisions are included.
- [ ] Uncertain database writes are not blindly retried.

### Background Work

- [ ] Long-lived tasks have an explicit supervisor.
- [ ] Background task exceptions are observed.
- [ ] Scheduled jobs are idempotent.
- [ ] Job arguments remain serializable.
- [ ] APScheduler lifecycle is application-owned.
- [ ] Duplicate scheduling and overlapping execution are controlled.
- [ ] Shutdown does not silently abandon application-owned tasks.

### Performance and Validation

- [ ] No blocking operation was added to the event loop.
- [ ] CPU-heavy work uses an appropriate execution model.
- [ ] Concurrency limits are tested.
- [ ] Cancellation and timeout behavior are tested.
- [ ] Partial failure handling is tested.
- [ ] Relevant regression tests pass.
- [ ] Project CI/CD validation requirements are satisfied.

---

## 18. Authoritative Technical References

Implementation decisions must remain consistent with the project's pinned dependency versions and official documentation.

**Python and asyncio**

- [Python 3.14 asyncio Tasks, TaskGroup, gather, and Cancellation](https://docs.python.org/3.14/library/asyncio-task.html)
- [Python 3.14 asyncio Synchronization Primitives](https://docs.python.org/3.14/library/asyncio-sync.html)
- [Python 3.14 asyncio Queues](https://docs.python.org/3.14/library/asyncio-queue.html)
- [Python 3.14 asyncio Streams](https://docs.python.org/3.14/library/asyncio-stream.html)

**SQLAlchemy**

- [SQLAlchemy 2.0 Asynchronous I/O](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [SQLAlchemy 2.0 Session Basics and Concurrent Session Safety](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
- [SQLAlchemy 2.0 Connection Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)

**APScheduler**

- [APScheduler 3.x AsyncIOScheduler](https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/asyncio.html)
- [APScheduler 3.x SQLAlchemyJobStore](https://apscheduler.readthedocs.io/en/3.x/modules/jobstores/sqlalchemy.html)
- [APScheduler 3.x User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html)

When documentation examples conflict with the project's established abstractions, follow the official API behavior and the actual implementation contracts. Do not assume that an API available in another major or minor dependency version exists in the project's pinned version.

---

**Final Engineering Standard**

TCF Bot's asynchronous architecture must prioritize structured execution, bounded resource consumption, explicit failure semantics, cancellation safety, transaction integrity, and operational observability.

`asyncio.TaskGroup` is the default for coordinated concurrent work. `asyncio.gather()` remains available for use cases where its distinct semantics are intentional. `gather_bounded()` and `fan_out()` remain the project-level boundaries for bounded database bursts and federation-wide Telegram operations, respectively.

No optimization is acceptable if it introduces uncontrolled concurrency, hidden failures, leaked tasks, unsafe database sessions, or unpredictable application shutdown.