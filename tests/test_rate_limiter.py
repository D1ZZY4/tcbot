# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for the _RateLimiter sliding-window implementation in decorators.py."""

from __future__ import annotations

import time

from tcbot.modules.helper.decorators import _RateLimiter

# ───────────────────────────── Helpers ──────────────────────────── #


def make_rl(max_calls: int = 3, window: float = 10.0) -> _RateLimiter:
    return _RateLimiter(max_calls=max_calls, window=window)


# ────────────────────── Complex Allow / Deny ────────────────────── #


class TestAllowDeny:
    def test_first_call_always_allowed(self):
        rl = make_rl()
        assert rl.check(1) == 0.0

    def test_calls_within_limit_all_allowed(self):
        rl = make_rl(max_calls=3)
        for _ in range(3):
            assert rl.check(1) == 0.0

    def test_call_over_limit_is_denied(self):
        rl = make_rl(max_calls=3)
        for _ in range(3):
            rl.check(1)
        wait = rl.check(1)
        assert wait > 0.0

    def test_denied_call_returns_positive_wait(self):
        rl = make_rl(max_calls=1, window=10.0)
        rl.check(1)
        wait = rl.check(1)
        assert 0.0 < wait <= 10.0

    def test_denied_call_not_recorded(self):
        """Blocked call must NOT consume a slot - only allowed calls are recorded."""
        rl = make_rl(max_calls=2, window=10.0)
        rl.check(1)  # * slot 1
        rl.check(1)  # * slot 2 - now full
        rl.check(1)  # * blocked - must NOT record
        rl.check(1)  # * still blocked
        wait = rl.check(1)
        assert wait > 0.0  # * still throttled, not suddenly freed


# ─────────────────────── Per-user isolation ─────────────────────── #


class TestPerUserIsolation:
    def test_different_users_are_independent(self):
        rl = make_rl(max_calls=2)
        rl.check(1)
        rl.check(1)
        # * user 1 is now throttled
        assert rl.check(1) > 0.0
        # * user 2 should still be free
        assert rl.check(2) == 0.0

    def test_user_a_throttle_does_not_affect_user_b(self):
        rl = make_rl(max_calls=1)
        rl.check(100)
        rl.check(100)  # * 100 throttled
        for uid in range(101, 111):
            assert rl.check(uid) == 0.0, f"uid {uid} was incorrectly throttled"


# ────────────────────────── Window expiry ───────────────────────── #


class TestWindowExpiry:
    def test_expired_window_resets_allow(self, monkeypatch):
        rl = make_rl(max_calls=2, window=1.0)
        base = time.monotonic()
        calls = iter([base, base, base + 2.0, base + 2.0])
        monkeypatch.setattr(
            "tcbot.modules.helper.decorators.time.monotonic", lambda: next(calls)
        )

        assert rl.check(1) == 0.0  # * t=base   slot 1
        assert rl.check(1) == 0.0  # * t=base   slot 2 - full
        assert rl.check(1) == 0.0  # * t=base+2 window expired - allowed again
        assert rl.check(1) == 0.0  # * t=base+2 slot 2 again - still allowed

    def test_partial_expiry_keeps_remaining_slots(self, monkeypatch):
        """Two calls at t=0, one at t=0.  At t=5 only the two t=0 calls expired."""
        rl = make_rl(max_calls=3, window=5.0)
        base = time.monotonic()
        # t=0: three calls fill the bucket
        seq = [base, base, base, base + 6.0]
        monkeypatch.setattr(
            "tcbot.modules.helper.decorators.time.monotonic", lambda: seq.pop(0)
        )

        rl.check(1)  # * slot 1 @ t=0
        rl.check(1)  # * slot 2 @ t=0
        rl.check(1)  # * slot 3 @ t=0  - full
        # at t+6 all three have expired → allowed fresh
        assert rl.check(1) == 0.0


# ───────────────────────── Memory hygiene ───────────────────────── #


class TestMemoryHygiene:
    def test_stale_bucket_pruned_after_window(self, monkeypatch):
        rl = make_rl(max_calls=3, window=1.0)
        base = time.monotonic()
        times = iter([base, base + 2.0])
        monkeypatch.setattr(
            "tcbot.modules.helper.decorators.time.monotonic", lambda: next(times)
        )

        rl.check(42)  # * creates bucket
        assert 42 in rl._buckets

        rl.check(42)  # * t+2: window expired → bucket recycled → allowed
        # * bucket must still exist (fresh entry written for this call)
        assert 42 in rl._buckets
        assert len(rl._buckets[42]) == 1

    def test_unknown_user_not_in_buckets_before_first_call(self):
        rl = make_rl()
        assert 999 not in rl._buckets


# ─────────────────────────── Edge cases ─────────────────────────── #


class TestEdgeCases:
    def test_max_calls_one(self):
        rl = make_rl(max_calls=1, window=60.0)
        assert rl.check(7) == 0.0
        assert rl.check(7) > 0.0

    def test_large_uid(self):
        rl = make_rl(max_calls=5)
        uid = 9_999_999_999
        for _ in range(5):
            assert rl.check(uid) == 0.0
        assert rl.check(uid) > 0.0

    def test_wait_value_bounded_by_window(self):
        rl = make_rl(max_calls=1, window=30.0)
        rl.check(1)
        wait = rl.check(1)
        assert 0.0 < wait <= 30.0

    def test_slots_attribute(self):
        rl = make_rl()
        assert hasattr(rl, "__slots__")
