"""Откат часов назад: last = max(last, now), поэтому время не начисляется дважды."""


def test_rollback_adds_no_tokens(limiter_cls):
    lim = limiter_cls(10, 1)
    lim.consume("a", 1, now=10.0)  # 9 токенов
    assert lim.peek("a", now=0.0) == 9.0  # отрицательный elapsed не отнимает токены
    assert lim.consume("a", 1, now=5.0).remaining == 8.0


def test_rollback_does_not_credit_time_twice(limiter_cls):
    lim = limiter_cls(10, 1)
    lim.consume("a", 10, now=10.0)  # пусто, last=10

    denied = lim.consume("a", 1, now=5.0)  # часы ушли назад на 5 с
    assert (denied.allowed, denied.remaining, denied.retry_after) == (False, 0.0, 1.0)

    # Если бы last откатился до 5, при возврате к t=10 мы бы снова начислили 5 с.
    assert lim.peek("a", now=10.0) == 0.0
    assert lim.peek("a", now=11.0) == 1.0


def test_purge_ignores_buckets_from_the_future(limiter_cls):
    lim = limiter_cls(1, 1)
    lim.consume("a", now=100.0)
    assert lim.purge(0, now=50.0) == 0
