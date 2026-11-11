"""Поведение Limiter. Каждый тест запускается на C++ и на чистом Python."""

import math

import pytest


def as_tuple(decision):
    return (decision.allowed, decision.remaining, decision.retry_after)


# --- consume -----------------------------------------------------------------


def test_scenario_table(limiter_cls):
    lim = limiter_cls(2, 1)
    assert as_tuple(lim.consume("a", now=0.0)) == (True, 1.0, 0.0)
    assert as_tuple(lim.consume("a", now=0.0)) == (True, 0.0, 0.0)
    assert as_tuple(lim.consume("a", now=0.0)) == (False, 0.0, 1.0)
    assert as_tuple(lim.consume("a", now=0.5)) == (False, 0.5, 0.5)
    assert as_tuple(lim.consume("a", now=10.0)) == (True, 1.0, 0.0)  # потолок capacity


def test_new_key_starts_full(limiter_cls):
    lim = limiter_cls(5, 1)
    assert lim.consume("new", 5, now=123.0).allowed


def test_cost_default_is_one(limiter_cls):
    lim = limiter_cls(3, 1)
    assert lim.consume("a", now=0.0).remaining == 2.0


def test_cost_equal_to_capacity_is_allowed(limiter_cls):
    lim = limiter_cls(2, 1)
    assert as_tuple(lim.consume("a", 2, now=0.0)) == (True, 0.0, 0.0)


def test_fractional_refill_is_not_lost(limiter_cls):
    # rate=3/с, вызовы каждые 0.1 с: целочисленные токены здесь никогда бы не пополнились.
    lim = limiter_cls(10, 3)
    lim.consume("a", 10, now=0.0)
    allowed = sum(lim.allow("a", now=round(0.1 * i, 10)) for i in range(1, 11))
    assert allowed == 3


def test_denied_request_does_not_consume(limiter_cls):
    lim = limiter_cls(2, 1)
    lim.consume("a", 2, now=0.0)
    assert not lim.allow("a", 1, now=0.5)
    assert lim.peek("a", now=0.5) == 0.5


def test_keys_are_independent(limiter_cls):
    lim = limiter_cls(1, 1)
    assert lim.allow("a", now=0.0)
    assert not lim.allow("a", now=0.0)
    assert lim.allow("b", now=0.0)


def test_without_now_uses_monotonic_clock(limiter_cls):
    lim = limiter_cls(1, 1e-9)
    assert lim.allow("a")
    assert not lim.allow("a")


def test_now_is_keyword_only(limiter_cls):
    lim = limiter_cls(2, 1)
    with pytest.raises(TypeError):
        lim.consume("a", 1, 5.0)


# --- валидация ---------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, math.nan])
def test_invalid_capacity_or_rate(limiter_cls, bad):
    with pytest.raises(ValueError, match="capacity"):
        limiter_cls(bad, 1)
    with pytest.raises(ValueError, match="rate"):
        limiter_cls(1, bad)


@pytest.mark.parametrize("bad", [0, -1, math.nan])
def test_invalid_cost(limiter_cls, bad):
    lim = limiter_cls(2, 1)
    with pytest.raises(ValueError, match="cost"):
        lim.consume("a", bad, now=0.0)


def test_cost_greater_than_capacity(limiter_cls):
    lim = limiter_cls(2, 1)
    with pytest.raises(ValueError, match="capacity"):
        lim.consume("a", 3, now=0.0)
    assert len(lim) == 0


# --- peek ----------------------------------------------------------------------


def test_peek_unknown_key_is_full_and_not_created(limiter_cls):
    lim = limiter_cls(4, 1)
    assert lim.peek("ghost", now=0.0) == 4.0
    assert len(lim) == 0


def test_peek_shows_refill_without_changing_state(limiter_cls):
    lim = limiter_cls(2, 1)
    lim.consume("a", 2, now=0.0)
    assert lim.peek("a", now=10.0) == 2.0
    # Если бы peek сохранил пополнение (last=10, tokens=2), здесь остался бы 1 токен.
    assert as_tuple(lim.consume("a", 1, now=1.0)) == (True, 0.0, 0.0)


# --- reset / purge / len -------------------------------------------------------


def test_reset(limiter_cls):
    lim = limiter_cls(1, 1)
    lim.consume("a", now=0.0)
    assert lim.reset("a") is True
    assert lim.reset("a") is False
    assert lim.allow("a", now=0.0)  # после reset бакет снова полный


def test_purge_removes_only_idle_and_full(limiter_cls):
    lim = limiter_cls(10, 1)
    for i in range(100):
        lim.consume(f"user{i}", 1, now=0.0)  # к t=100 давно полные
    lim.consume("recent", 1, now=99.0)  # полный, но использован недавно
    assert lim.purge(60, now=100.0) == 100
    assert len(lim) == 1
    assert lim.peek("recent", now=100.0) == 10.0


def test_purge_keeps_idle_but_not_full(limiter_cls):
    # Удалить такой бакет = подарить клиенту полный бакет и обойти лимит.
    lim = limiter_cls(10, 0.001)
    lim.consume("slow", 10, now=0.0)
    assert lim.purge(60, now=100.0) == 0
    assert not lim.allow("slow", now=100.0)


def test_len(limiter_cls):
    lim = limiter_cls(1, 1)
    assert len(lim) == 0
    lim.consume("a", now=0.0)
    lim.consume("b", now=0.0)
    lim.consume("a", now=0.0)
    assert len(lim) == 2


# --- атрибуты и repr -----------------------------------------------------------


def test_properties_are_floats(limiter_cls):
    lim = limiter_cls(10, 2)
    assert (lim.capacity, lim.rate) == (10.0, 2.0)
    assert isinstance(lim.capacity, float)


def test_repr(limiter_cls):
    lim = limiter_cls(2, 1)
    lim.consume("a", now=0.0)
    assert repr(lim) == "Limiter(capacity=2.0, rate=1.0, size=1)"
    assert repr(lim.consume("a", now=0.0)) == "Decision(allowed=True, remaining=0.0, retry_after=0.0)"


def test_decision_is_read_only(limiter_cls):
    decision = limiter_cls(1, 1).consume("a", now=0.0)
    with pytest.raises(AttributeError):
        decision.allowed = False
