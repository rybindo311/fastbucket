"""Многопоточность на уровне Python API.

Биндинг не отпускает GIL, поэтому вызовы C++ из разных потоков чередуются,
а не идут параллельно. Настоящие гонки внутри ядра ловит ThreadSanitizer
на C++-уровне; здесь проверяем, что под конкурентной нагрузкой лимит
соблюдается точно и состояние остаётся согласованным.
"""

from concurrent.futures import ThreadPoolExecutor

THREADS = 8
CALLS_PER_THREAD = 2_000


def test_shared_key_allows_exactly_capacity(limiter_cls):
    capacity = 1_000
    lim = limiter_cls(capacity, 1e-9)  # пополнение пренебрежимо мало

    def worker(_):
        return sum(lim.allow("shared", now=0.0) for _ in range(CALLS_PER_THREAD))

    with ThreadPoolExecutor(THREADS) as pool:
        allowed = sum(pool.map(worker, range(THREADS)))

    assert allowed == capacity
    assert lim.peek("shared", now=0.0) == 0.0


def test_mixed_operations_keep_state_consistent(limiter_cls):
    lim = limiter_cls(5, 1)

    def worker(tid):
        for i in range(CALLS_PER_THREAD):
            key = f"k{i % 50}"
            now = float(i)
            lim.consume(key, now=now)
            lim.peek(key, now=now)
            if i % 97 == 0:
                lim.reset(key)
            if i % 501 == 0:
                lim.purge(10, now=now)
        return tid

    with ThreadPoolExecutor(THREADS) as pool:
        assert sorted(pool.map(worker, range(THREADS))) == list(range(THREADS))

    assert 0 <= len(lim) <= 50
    for i in range(50):
        assert 0.0 <= lim.peek(f"k{i}", now=1e9) <= 5.0
