"""Эталонная реализация fastbucket на чистом Python.

Повторяет ``src/cpp/token_bucket.hpp`` операция в операцию: те же формулы
в том же порядке, те же ``min``/``max``. Благодаря этому обе реализации дают
побитово одинаковые ``float`` (IEEE 754 округляет каждую операцию однозначно),
и тесты сравнивают их через ``==`` (см. ``tests/test_equivalence.py``).

Используется как оракул в тестах и как базовая линия в бенчмарках.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

__all__ = ["Decision", "Limiter"]


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    remaining: float
    retry_after: float


class _Bucket:
    __slots__ = ("last", "tokens")

    def __init__(self, last: float, tokens: float) -> None:
        self.last = last
        self.tokens = tokens


def _as_float(value: object, name: str) -> float:
    # pybind11 не превращает строки в double, float("1.5") — превращает.
    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a number, not {type(value).__name__}")
    return float(value)  # type: ignore[arg-type]


def _validate(value: object, name: str) -> float:
    number = _as_float(value, name)
    if number > 0.0:  # NaN тоже не проходит: любое сравнение с NaN ложно
        return number
    raise ValueError(f"{name} must be greater than zero")


def _now(now: object) -> float:
    return time.monotonic() if now is None else _as_float(now, "now")


class Limiter:
    __slots__ = ("_capacity", "_rate", "_buckets", "_lock")

    def __init__(self, capacity: float, rate: float) -> None:
        self._capacity = _validate(capacity, "capacity")
        self._rate = _validate(rate, "rate")
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    @property
    def capacity(self) -> float:
        return self._capacity

    @property
    def rate(self) -> float:
        return self._rate

    # Порядок аргументов min/max совпадает с std::min/std::max в C++:
    # при равенстве оба возвращают первый аргумент.
    def _refill(self, bucket: _Bucket, now: float) -> None:
        elapsed = max(0.0, now - bucket.last)
        bucket.last = max(bucket.last, now)
        bucket.tokens = min(self._capacity, bucket.tokens + self._rate * elapsed)

    def _tokens_at(self, bucket: _Bucket, now: float) -> float:
        copy = _Bucket(bucket.last, bucket.tokens)
        self._refill(copy, now)
        return copy.tokens

    def consume(self, key: str, cost: float = 1.0, *, now: float | None = None) -> Decision:
        if not isinstance(key, str):
            raise TypeError(f"key must be str, not {type(key).__name__}")
        cost = _validate(cost, "cost")
        if cost > self._capacity:
            raise ValueError("cost greater than capacity")
        t = _now(now)

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = self._buckets[key] = _Bucket(t, self._capacity)
            self._refill(bucket, t)

            if bucket.tokens < cost:
                return Decision(False, bucket.tokens, (cost - bucket.tokens) / self._rate)

            bucket.tokens -= cost
            return Decision(True, bucket.tokens, 0.0)

    def allow(self, key: str, cost: float = 1.0, *, now: float | None = None) -> bool:
        return self.consume(key, cost, now=now).allowed

    def peek(self, key: str, *, now: float | None = None) -> float:
        t = _now(now)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._capacity
            return self._tokens_at(bucket, t)

    def reset(self, key: str) -> bool:
        with self._lock:
            return self._buckets.pop(key, None) is not None

    def purge(self, idle: float, *, now: float | None = None) -> int:
        idle = _as_float(idle, "idle")
        t = _now(now)
        with self._lock:
            stale = [
                key
                for key, bucket in self._buckets.items()
                if t - bucket.last >= idle and self._tokens_at(bucket, t) == self._capacity
            ]
            for key in stale:
                del self._buckets[key]
            return len(stale)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buckets)

    def __repr__(self) -> str:
        return f"Limiter(capacity={self._capacity}, rate={self._rate}, size={len(self)})"
