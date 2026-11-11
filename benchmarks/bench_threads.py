"""Масштабирование по потокам: C++ ядро против чистого Python.

Запуск:
    poetry run python benchmarks/bench_threads.py

Общее число вызовов фиксировано и делится между потоками. Биндинг не
отпускает GIL, поэтому ожидаемо ни одна реализация не ускоряется с ростом
числа потоков: вызовы выполняются по очереди. Скрипт печатает таблицу
в Markdown, её можно вставить в README.
"""

from __future__ import annotations

import statistics
import sys
import threading
import time

import fastbucket
from fastbucket import _pure

TOTAL_CALLS = 400_000
THREADS = (1, 2, 4, 8)
REPEATS = 5
BIG = 1e9
NOW = 1.0

IMPLEMENTATIONS = {"cpp": fastbucket.Limiter, "pure": _pure.Limiter}


def run_once(limiter_cls, threads: int, shared_key: bool) -> float:
    lim = limiter_cls(BIG, BIG)
    per_thread = TOTAL_CALLS // threads
    barrier = threading.Barrier(threads + 1)

    def worker(tid: int) -> None:
        key = "shared" if shared_key else f"user{tid}"
        consume = lim.consume
        barrier.wait()
        for _ in range(per_thread):
            consume(key, 1.0, now=NOW)

    pool = [threading.Thread(target=worker, args=(t,)) for t in range(threads)]
    for t in pool:
        t.start()
    barrier.wait()
    start = time.perf_counter()
    for t in pool:
        t.join()
    return time.perf_counter() - start


def main() -> None:
    gil = "включён" if getattr(sys, "_is_gil_enabled", lambda: True)() else "выключен"
    print(f"Python {sys.version.split()[0]}, GIL {gil}, {TOTAL_CALLS:,} вызовов, медиана из {REPEATS}\n")
    print("| Реализация | Ключи | " + " | ".join(f"{n} пот." for n in THREADS) + " |")
    print("|---|---|" + "---:|" * len(THREADS))

    for name, cls in IMPLEMENTATIONS.items():
        for shared in (True, False):
            cells = []
            for n in THREADS:
                seconds = statistics.median(run_once(cls, n, shared) for _ in range(REPEATS))
                cells.append(f"{TOTAL_CALLS / seconds / 1e6:.2f} M/с")
            keys = "общий" if shared else "свой у потока"
            print(f"| {name} | {keys} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
