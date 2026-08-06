"""Focused regression tests for webhook delivery and Redis cache ordering."""

from __future__ import annotations

import asyncio
import json
import threading
import unittest
from datetime import UTC, datetime
from typing import ClassVar
from unittest.mock import patch

from bson import ObjectId

from tcbot import alive
from tcbot.database import cache as cache_mod
from tcbot.database import scheduler as scheduler_mod


class _FakeBot:
    """Minimal bot object accepted by the webhook registration seam."""


class _BlockingQueue:
    """Queue double whose put waits until the test releases it."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    async def put(self, _value: object) -> None:
        self.started.set()
        await asyncio.to_thread(self.release.wait)


class _FailingQueue:
    """Queue double that rejects every update."""

    async def put(self, _value: object) -> None:
        raise RuntimeError("queue unavailable")


class WebhookRouteTests(unittest.TestCase):
    """Verify that Telegram receives retryable responses for enqueue failures."""

    _UPDATE: ClassVar[dict[str, int]] = {"update_id": 1}

    def setUp(self) -> None:
        """Start an event loop in a worker thread for the Flask route."""
        self.client = alive._app.test_client()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        """Stop the worker loop and clear the webhook registration globals."""
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
        self._loop.close()
        alive._wh_queue = None
        alive._wh_loop = None
        alive._wh_secret = ""
        alive._wh_bot = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _post(self) -> tuple[int, str]:
        response = self.client.post(
            "/webhook",
            json=self._UPDATE,
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        )
        return response.status_code, response.get_data(as_text=True)

    def _patch_update(self):
        return patch.object(
            alive.Update,
            "de_json",
            return_value=object(),
        )

    def test_enqueue_success_returns_ok(self) -> None:
        """Return 200 only after the update reaches the PTB queue."""
        queue: asyncio.Queue[object] = asyncio.Queue()
        alive.register_webhook(queue, self._loop, "secret", _FakeBot())

        with self._patch_update():
            status, body = self._post()

        self.assertEqual((status, body), (200, "OK"))
        self.assertIsNotNone(queue.get_nowait())

    def test_enqueue_exception_returns_service_unavailable(self) -> None:
        """Return 503 when PTB rejects the queued update."""
        alive.register_webhook(_FailingQueue(), self._loop, "secret", _FakeBot())

        with self._patch_update():
            status, body = self._post()

        self.assertEqual((status, body), (503, "Service unavailable"))

    def test_enqueue_timeout_returns_service_unavailable(self) -> None:
        """Return 503 when queue insertion exceeds the bounded wait."""
        queue = _BlockingQueue()
        alive.register_webhook(queue, self._loop, "secret", _FakeBot())

        with (
            self._patch_update(),
            patch.object(alive, "_WEBHOOK_ENQUEUE_TIMEOUT_S", 0.01),
        ):
            status, body = self._post()

        self.assertEqual((status, body), (503, "Service unavailable"))
        queue.release.set()


class _FakeRedis:
    """Small Redis double used to observe mutation ordering."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.set_started = asyncio.Event()
        self.release_set = asyncio.Event()

    async def set(self, _key: str, _value: str, *, ex: int) -> None:
        del ex
        self.set_started.set()
        await self.release_set.wait()
        self.events.append("set")

    async def delete(self, _key: str) -> None:
        self.events.append("delete")

    async def scan(
        self, _cursor: int, *, match: str, count: int
    ) -> tuple[int, list[str]]:
        del match, count
        self.events.append("scan")
        return 0, ["tcbot:test:v2:key"]

    async def unlink(self, *_keys: str) -> None:
        self.events.append("unlink")

    async def get(self, _key: str) -> str | None:
        return None


class CacheTests(unittest.IsolatedAsyncioTestCase):
    """Verify ordered mutations and typed Redis JSON round-trips."""

    async def test_mutations_are_fifo(self) -> None:
        """Delete a key only after its preceding write completes."""
        redis = _FakeRedis()
        cache = cache_mod.TwoLevelCache[str](
            memory_ttl=60,
            redis_ttl=60,
            redis_prefix="test",
        )
        other_cache = cache_mod.TwoLevelCache[str](
            memory_ttl=60,
            redis_ttl=60,
            redis_prefix="test",
        )
        with patch.object(cache_mod, "_redis_client", return_value=redis):
            cache.put("key", "value")
            await asyncio.wait_for(redis.set_started.wait(), timeout=1)
            other_cache.invalidate("key")
            redis.release_set.set()
            tail = cache_mod._redis_tails[("test", asyncio.get_running_loop())]
            self.assertIsNotNone(tail)
            await tail

        self.assertEqual(redis.events, ["set", "delete"])

    async def test_clear_all_waits_for_prior_mutation(self) -> None:
        """Run a prefix sweep after earlier queued mutations finish."""
        redis = _FakeRedis()
        cache = cache_mod.TwoLevelCache[str](
            memory_ttl=60,
            redis_ttl=60,
            redis_prefix="test",
        )
        with patch.object(cache_mod, "_redis_client", return_value=redis):
            cache.put("key", "value")
            await asyncio.wait_for(redis.set_started.wait(), timeout=1)
            clear_task = asyncio.create_task(cache.clear_all())
            await asyncio.sleep(0)
            self.assertEqual(redis.events, [])
            redis.release_set.set()
            await clear_task

        self.assertEqual(redis.events, ["set", "scan", "unlink"])

    async def test_mongo_values_keep_their_types(self) -> None:
        """Restore datetime and ObjectId values from tagged JSON."""
        timestamp = datetime(2026, 8, 5, 12, 30, tzinfo=UTC)
        object_id = ObjectId("507f1f77bcf86cd799439011")
        encoded = json.dumps(
            {"timestamp": timestamp, "_id": object_id},
            cls=cache_mod._MongoJSONEncoder,
        )
        decoded = json.loads(encoded, object_hook=cache_mod._mongo_object_hook)

        self.assertEqual(decoded["timestamp"], timestamp)
        self.assertIsInstance(decoded["timestamp"], datetime)
        self.assertEqual(decoded["_id"], object_id)
        self.assertIsInstance(decoded["_id"], ObjectId)


class SchedulerReadinessTests(unittest.IsolatedAsyncioTestCase):
    """Verify that scheduler health reflects completed startup only."""

    async def test_readiness_waits_for_successful_initialization(self) -> None:
        """Keep health degraded during partial startup and after an error."""
        ready = asyncio.Event()
        with (
            patch.object(scheduler_mod, "_scheduler", object()),
            patch.object(scheduler_mod, "_sched_ready", ready),
            patch.object(scheduler_mod, "_sched_error", None),
        ):
            self.assertFalse(scheduler_mod.is_ready())
            ready.set()
            self.assertTrue(scheduler_mod.is_ready())
            scheduler_mod._sched_error = RuntimeError("startup failed")
            self.assertFalse(scheduler_mod.is_ready())

    async def test_start_propagates_background_startup_error(self) -> None:
        """Raise scheduler initialization failures instead of reporting ready."""

        async def fail_background(
            _mongodb_uri: str, _db_name: str, _warn_expiry_days: int
        ) -> None:
            scheduler_mod._sched_error = RuntimeError("startup failed")
            assert scheduler_mod._sched_ready is not None
            scheduler_mod._sched_ready.set()

        with (
            patch.object(scheduler_mod, "_scheduler_background", fail_background),
            self.assertRaisesRegex(RuntimeError, "APScheduler failed to start"),
        ):
            await scheduler_mod.start("mongodb://example", "tcbot", 0)

        self.assertFalse(scheduler_mod.is_ready())


if __name__ == "__main__":
    unittest.main()
