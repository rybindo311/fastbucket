"""Однопоточные бенчмарки: C++ ядро против чистого Python.

Запуск:
    poetry run pytest benchmarks/bench_limiter.py

Каждый замер — цикл из CALLS вызовов, поэтому время на вызов = Mean / CALLS.
Цикл и обращение к методу одинаковы для обеих реализаций; базовая линия
`noop` показывает, сколько из этого стоит сам вызов Python-функции.

Бакеты очень большие (capacity=1e9), а now фиксирован, поэтому за время
замера бакет не пустеет и измеряется основной путь «разрешено и списано».
"""

import pytest

CALLS = 10_000
KEYS = 100_000
NOW = 1.0
BIG = 1e9


def per_call(benchmark) -> None:
    benchmark.extra_info["calls_per_round"] = CALLS


# --- базовая линия -----------------------------------------------------------------


@pytest.mark.benchmark(group="consume: 1 ключ")
def test_noop_python_call(benchmark):
    def noop(key, cost=1.0, *, now=None):
        return None

    def run():
        for _ in range(CALLS):
            noop("user", 1.0, now=NOW)

    per_call(benchmark)
    benchmark(run)


# --- consume -----------------------------------------------------------------------


@pytest.mark.benchmark(group="consume: 1 ключ")
def test_consume_single_key(benchmark, limiter_cls):
    lim = limiter_cls(BIG, BIG)
    consume = lim.consume

    def run():
        for _ in range(CALLS):
            consume("user", 1.0, now=NOW)

    per_call(benchmark)
    benchmark(run)


@pytest.mark.benchmark(group="consume: 1 ключ, now=None")
def test_consume_single_key_live_clock(benchmark, limiter_cls):
    lim = limiter_cls(BIG, BIG)
    consume = lim.consume

    def run():
        for _ in range(CALLS):
            consume("user")

    per_call(benchmark)
    benchmark(run)


@pytest.mark.benchmark(group=f"consume: {KEYS:,} ключей".replace(",", " "))
def test_consume_many_keys(benchmark, limiter_cls):
    lim = limiter_cls(BIG, BIG)
    keys = [f"user{i}" for i in range(KEYS)]
    for key in keys:  # бакеты уже созданы: меряем поиск, а не вставку
        lim.consume(key, 1.0, now=NOW)
    consume = lim.consume
    batch = keys[::KEYS // CALLS]  # CALLS ключей, разбросанных по всему словарю

    def run():
        for key in batch:
            consume(key, 1.0, now=NOW)

    per_call(benchmark)
    benchmark(run)


# --- peek и purge --------------------------------------------------------------------


@pytest.mark.benchmark(group="peek: 1 ключ")
def test_peek_single_key(benchmark, limiter_cls):
    lim = limiter_cls(BIG, BIG)
    lim.consume("user", 1.0, now=NOW)
    peek = lim.peek

    def run():
        for _ in range(CALLS):
            peek("user", now=NOW)

    per_call(benchmark)
    benchmark(run)


@pytest.mark.benchmark(group=f"purge: обход {KEYS:,} бакетов".replace(",", " "))
def test_purge_scan(benchmark, limiter_cls):
    # Бакеты не полные, поэтому ничего не удаляется и каждый раунд
    # обходит все KEYS бакетов — столько времени purge держит мьютекс.
    lim = limiter_cls(10, 1e-9)
    for i in range(KEYS):
        lim.consume(f"user{i}", 5, now=0.0)

    benchmark(lim.purge, 60, now=100.0)
    assert len(lim) == KEYS
