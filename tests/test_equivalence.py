"""C++ и чистый Python дают побитово одинаковые результаты.

Hypothesis генерирует случайные последовательности операций (включая откат
часов) и выполняет их на обеих реализациях. Сравнение строгое (==), без
approx: формулы совпадают операция в операцию, а сборка C++ идёт с
-ffp-contract=off. Любое расхождение — реальная разница в логике.
"""

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

import fastbucket
from fastbucket import _pure

KEYS = st.sampled_from(["a", "b", "c"])


def as_tuple(decision):
    return (decision.allowed, decision.remaining, decision.retry_after)


class SameBehaviour(RuleBasedStateMachine):
    @initialize(
        capacity=st.floats(min_value=0.5, max_value=1_000),
        rate=st.floats(min_value=0.001, max_value=1_000),
    )
    def create(self, capacity, rate):
        self.cpp = fastbucket.Limiter(capacity, rate)
        self.pure = _pure.Limiter(capacity, rate)
        self.now = 0.0

    @rule(dt=st.floats(min_value=-5, max_value=50))
    def tick(self, dt):
        self.now += dt

    @rule(key=KEYS, fraction=st.floats(min_value=0.001, max_value=1.0))
    def consume(self, key, fraction):
        cost = self.cpp.capacity * fraction
        got = as_tuple(self.cpp.consume(key, cost, now=self.now))
        expected = as_tuple(self.pure.consume(key, cost, now=self.now))
        assert got == expected

        allowed, remaining, retry_after = got
        assert 0.0 <= remaining <= self.cpp.capacity
        assert (retry_after == 0.0) if allowed else (retry_after > 0.0)

    @rule(key=KEYS)
    def peek(self, key):
        assert self.cpp.peek(key, now=self.now) == self.pure.peek(key, now=self.now)

    @rule(key=KEYS)
    def reset(self, key):
        assert self.cpp.reset(key) == self.pure.reset(key)

    @rule(idle=st.floats(min_value=0, max_value=100))
    def purge(self, idle):
        assert self.cpp.purge(idle, now=self.now) == self.pure.purge(idle, now=self.now)

    @invariant()
    def same_size(self):
        assert len(self.cpp) == len(self.pure)


TestSameBehaviour = SameBehaviour.TestCase
TestSameBehaviour.settings = settings(max_examples=300, stateful_step_count=50, deadline=None)
