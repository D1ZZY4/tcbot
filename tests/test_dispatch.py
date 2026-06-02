# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.utils.dispatch.fan_out."""

from __future__ import annotations

import asyncio

from tcbot.utils.dispatch import fan_out


class TestFanOutEmpty:
    async def test_empty_returns_empty_list(self):
        result = await fan_out([])
        assert result == []

    async def test_empty_no_exception(self):
        result = await fan_out([], max_concurrent=1)
        assert result == []


class TestFanOutSuccess:
    async def test_single_coroutine(self):
        async def coro():
            return 42

        result = await fan_out([coro()])
        assert result == [42]

    async def test_multiple_coroutines(self):
        async def coro(n: int):
            return n * 2

        result = await fan_out([coro(1), coro(2), coro(3)])
        assert result == [2, 4, 6]

    async def test_preserves_order(self):
        order: list[int] = []

        async def coro(n: int):
            await asyncio.sleep(0)
            order.append(n)
            return n

        result = await fan_out([coro(10), coro(20), coro(30)])
        assert result == [10, 20, 30]

    async def test_returns_list(self):
        async def coro():
            return "ok"

        result = await fan_out([coro()])
        assert isinstance(result, list)


class TestFanOutExceptions:
    async def test_exception_returned_not_raised(self):
        async def fail():
            raise ValueError("intentional")

        result = await fan_out([fail()])
        assert len(result) == 1
        assert isinstance(result[0], ValueError)

    async def test_mixed_success_and_failure(self):
        async def ok():
            return "ok"

        async def fail():
            raise RuntimeError("boom")

        result = await fan_out([ok(), fail(), ok()])
        assert result[0] == "ok"
        assert isinstance(result[1], RuntimeError)
        assert result[2] == "ok"

    async def test_all_fail_returns_exceptions(self):
        async def fail(n: int):
            raise ValueError(str(n))

        result = await fan_out([fail(1), fail(2)])
        assert all(isinstance(r, ValueError) for r in result)
        assert len(result) == 2


class TestFanOutConcurrency:
    async def test_respects_max_concurrent(self):
        running = 0
        peak = 0

        async def coro():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

        await fan_out([coro() for _ in range(20)], max_concurrent=3)
        assert peak <= 3

    async def test_default_max_concurrent(self):
        running = 0
        peak = 0

        async def coro():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

        await fan_out([coro() for _ in range(30)])
        assert peak <= 10

    async def test_max_concurrent_1_serializes(self):
        order: list[int] = []

        async def coro(n: int):
            order.append(n)
            return n

        await fan_out([coro(i) for i in range(5)], max_concurrent=1)
        assert order == [0, 1, 2, 3, 4]

    async def test_large_batch_completes(self):
        async def coro(n: int):
            return n

        result = await fan_out([coro(i) for i in range(100)])
        assert len(result) == 100
        assert result == list(range(100))
