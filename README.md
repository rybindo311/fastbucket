# fastbucket

Rate limiter на алгоритме token bucket. Ядро написано на C++17, биндинги сделаны через pybind11, есть ASGI-middleware и демо-сервис на FastAPI.

```python
from fastbucket import Limiter

limiter = Limiter(capacity=10, rate=1)      # 10 запросов разом, затем 1 в секунду
decision = limiter.consume("user:42")
decision.allowed, decision.remaining, decision.retry_after
# (True, 9.0, 0.0)
```

## Возможности

- **Потокобезопасное ядро на C++.** Бакеты пополняются лениво, без таймеров и фоновых потоков.
- **Эталонная реализация на чистом Python** с тем же API. С ядром на C++ она совпадает **до бита**, это проверяется hypothesis-тестами.
- **ASGI-middleware** без зависимости от FastAPI или Starlette. Лимит считается по `X-API-Key` или по IP, в ответ добавляются заголовки `X-RateLimit-*`, при превышении возвращается `429` с `Retry-After`.
- **Демо-сервис на FastAPI** с эндпоинтами `/ping`, `/health` и `/stats` и фоновой очисткой неактивных бакетов.
- **Типы** (`py.typed`, `_core.pyi`) для mypy, pyright и IDE.

## Установка

Сборка из исходников. Понадобятся компилятор C++17 и Python 3.10+.

```bash
git clone https://github.com/rybindo311/fastbucket
cd fastbucket
poetry install
poetry run pip install -e . --no-build-isolation
```

Пакет собирается через [scikit-build-core](https://scikit-build-core.readthedocs.io/) и CMake. Poetry отвечает только за окружение разработки.

## Использование

### Лимитер

```python
from fastbucket import Limiter

limiter = Limiter(capacity=2, rate=1)       # бакет на 2 токена, +1 токен в секунду

limiter.consume("alice", now=0.0)           # Decision(allowed=True,  remaining=1.0, retry_after=0.0)
limiter.consume("alice", now=0.0)           # Decision(allowed=True,  remaining=0.0, retry_after=0.0)
limiter.consume("alice", now=0.0)           # Decision(allowed=False, remaining=0.0, retry_after=1.0)
limiter.consume("alice", now=0.5)           # Decision(allowed=False, remaining=0.5, retry_after=0.5)

limiter.allow("bob", cost=2)                # True — то же, что consume(...).allowed
limiter.peek("alice", now=10.0)             # 2.0 — текущие токены, состояние не меняется
limiter.reset("alice")                      # True — бакет удалён
limiter.purge(idle=60)                      # сколько неактивных бакетов удалено
len(limiter), limiter.capacity, limiter.rate
```

- **`now`** — время в секундах (`float`), передаётся только по имени. Если его не указать, берётся монотонное время (`steady_clock` в C++). Явный `now` нужен для детерминированных тестов. В одном лимитере не стоит смешивать вызовы с `now` и без него.
- **`cost`** — сколько токенов списать, по умолчанию `1`. Если `cost <= 0` или `cost > capacity`, выбрасывается `ValueError`.
- **При отказе токены не списываются.** `retry_after` показывает, через сколько секунд хватит токенов на этот `cost`.

### ASGI-middleware

```python
from fastapi import FastAPI
from fastbucket import Limiter
from fastbucket.asgi import RateLimitMiddleware, Stats

app = FastAPI()
stats = Stats()
app.add_middleware(
    RateLimitMiddleware,
    limiter=Limiter(capacity=10, rate=1),
    cost=1,
    exempt=("/health",),        # эти пути не лимитируются
    trust_forwarded=False,      # True — брать IP из X-Forwarded-For (только за своим прокси!)
    stats=stats,                # счётчики allowed / denied
)
```

Middleware написан на чистом ASGI, поэтому работает с любым ASGI-фреймворком.

**Ключ лимита** выбирается по порядку:
1. `key_func(scope)`, если она задана;
2. `X-API-Key` → `key: …`;
3. первый адрес из `X-Forwarded-For`, если включён `trust_forwarded` → `ip: …`;
4. IP клиента → `ip: …`;
5. иначе `anon`.

Префиксы `key:` и `ip:` не дают клиенту потратить чужой IP-лимит, прислав этот IP в `X-API-Key`.

**Заголовки:**

| Заголовок | Значение |
|---|---|
| `X-RateLimit-Limit` | `capacity` |
| `X-RateLimit-Remaining` | `floor(remaining)` — сколько целых запросов ещё можно сделать |
| `X-RateLimit-Reset` | `ceil((capacity − remaining) / rate)` — через сколько секунд бакет снова полный |
| `Retry-After` (только при 429) | `ceil(retry_after)` — целые секунды, округление вверх |

Тело ответа 429: `{"detail": "rate limit exceeded", "retry_after": 0.73}`. В теле `retry_after` указан точно, без округления.

### Демо-сервис

```bash
poetry run uvicorn fastbucket.service.app:create_app --factory
# или с параметрами из окружения:
FASTBUCKET_CAPACITY=5 FASTBUCKET_RATE=0.5 poetry run uvicorn fastbucket.service.app:from_env --factory
```

```bash
for i in $(seq 1 12); do curl -s -o /dev/null -w "%{http_code} " localhost:8000/ping; done; echo
# 200 200 200 200 200 200 200 200 200 200 429 429
curl -s localhost:8000/stats
# {"buckets":1,"capacity":10.0,"rate":1.0,"cost":1.0,"allowed":10,"denied":2,"purged":0}
```

| Эндпоинт | Лимит | Ответ |
|---|---|---|
| `GET /ping` | да | `{"pong": true}` |
| `GET /health` | нет | `{"status": "ok"}` |
| `GET /stats` | нет | число бакетов, параметры, счётчики. Ключи клиентов не выдаются |

Переменные окружения для `from_env`: `FASTBUCKET_CAPACITY`, `FASTBUCKET_RATE`, `FASTBUCKET_COST`, `FASTBUCKET_PURGE_IDLE`, `FASTBUCKET_PURGE_INTERVAL`.

## Как это устроено

```
 FastAPI / любое ASGI-приложение
            │
   RateLimitMiddleware          fastbucket.asgi — ключ, заголовки, 429
            │
   fastbucket.Limiter           pybind11-биндинги (fastbucket._core)
            │
   fastbucket::Limiter          C++17: unordered_map<string, Bucket> + mutex
```

### Ключевые решения

- **Ленивое пополнение.** Бакет хранит всего два `double`: `tokens` и `last`. Токены досчитываются при обращении: `tokens = min(capacity, tokens + rate · elapsed)`. Таймеров и фоновых потоков нет, 16 байт на ключ.
- **Токены в `double`, а не в целых.** При `rate = 3/с` и запросах каждые 0,1 с целочисленное пополнение каждый раз давало бы `0` токенов, и бакет не пополнялся бы никогда.
- **Откат часов.** Пополнение считается как `elapsed = max(0, now − last)`, а `last = max(last, now)`. Поэтому при откате часов токены не отнимаются, а один и тот же отрезок времени не начисляется дважды.
- **Безопасный `purge`.** Удаляются только бакеты, которые давно не использовались **и** уже снова полные. Если удалить полупустой бакет, клиент получит новый полный и обойдёт лимит.
- **Побитовая эквивалентность с Python.** `fastbucket._pure` повторяет формулы ядра операция в операцию. Hypothesis (stateful) выполняет случайные последовательности операций, включая откат часов, на обеих реализациях и сравнивает результаты через `==`, без `approx`. Чтобы это работало, ядро собирается с `-ffp-contract=off`: иначе компилятор склеит `a + b·c` в FMA, и результаты разойдутся на 1 ULP. Одного ULP достаточно, чтобы на границе `allowed` сменился с `True` на `False`.
- **GIL не отпускается.** Одиночный вызов `consume` короче, чем стоит освобождение и повторный захват GIL.

## Производительность

Intel Core i5-6400 (4 ядра, 2,7 ГГц), Linux, Python 3.12.3, GCC 13.3, `-O3` (Release), pybind11 3.1. Время на один вызов из Python, медиана. Бакеты не пустеют за время замера, поэтому меряется путь «разрешено и списано».

| Операция | C++ | Чистый Python | Ускорение |
|---|---:|---:|---:|
| Пустой вызов Python-функции (база) | — | 78 нс | — |
| `consume(key, 1.0, now=t)`, 1 ключ | 968 нс | 2 415 нс | ×2,5 |
| `consume(key)`, живые часы | 596 нс | 2 362 нс | ×4,0 |
| `consume`, 100 000 ключей вразброс | 1 335 нс | 2 899 нс | ×2,2 |
| `peek(key, now=t)` | 446 нс | 1 546 нс | ×3,5 |
| `purge`, обход 100 000 бакетов | 5,1 мс | 92 мс | ×18 |

Масштабирование по потокам: суммарно 400 000 вызовов `consume`, поделённых между потоками.

**Пропускная способность, млн вызовов/с:**
| Реализация | Ключи | 1 поток | 2 потока | 4 потока | 8 потоков |
|---|---|---:|---:|---:|---:|
| C++ | общий | 1,06 M/с | 1,10 M/с | 1,08 M/с | 1,08 M/с |
| C++ | свой у потока | 1,11 M/с | 1,10 M/с | 1,09 M/с | 1,07 M/с |
| Python | общий | 0,42 M/с | 0,14 M/с | 0,12 M/с | 0,12 M/с |
| Python | свой у потока | 0,41 M/с | 0,15 M/с | 0,13 M/с | 0,12 M/с |

### Что видно из цифр

- **Узкое место — граница Python/C++, а не алгоритм.** Ядро работает десятки наносекунд, а вызов из Python стоит сотни. Нагляднее всего это на `purge`: там один вызов делает 100 000 итераций внутри C++, и разрыв достигает ×18.
- **Именованные аргументы в pybind11 дорогие.** `consume("k", now=1.0)` занимает около 880 нс, а `consume("k")` — около 560 нс. Разбор `now=` обходится дороже, чем чтение `steady_clock`. Если нужна скорость, передавайте `now` только в тестах.
- **Потоки не ускоряют C++.** Биндинг держит GIL, и вызовы идут по очереди. Зато пропускная способность не падает. У чистого Python с ростом числа потоков она проседает втрое из-за борьбы за GIL и `threading.Lock`.
- **В HTTP-сервисе лимитер почти незаметен:** около 1 мкс на запрос на фоне десятков и сотен микросекунд, которые занимают uvicorn и FastAPI.

Как воспроизвести:

```bash
poetry run pytest benchmarks/bench_limiter.py
poetry run python benchmarks/bench_threads.py
```

## Разработка

```bash
poetry install
poetry run pip install -e . --no-build-isolation   # один раз
poetry run pytest                                  # 83 теста, обе реализации
```

- **Пересборка.** Включён `editable.rebuild`: после правок C++ модуль пересобирается сам при следующем `import fastbucket`.
- **Стаб.** После изменения биндингов перегенерируйте его:
  ```bash
  poetry run pybind11-stubgen fastbucket._core -o src
  ```
- **Тесты.** Большинство тестов запускается на обеих реализациях через фикстуру `limiter_cls`. Отдельно проверяются откат часов, потоки, middleware и сервис, а `test_equivalence.py` сравнивает C++ и Python через hypothesis.

### Структура

```
src/cpp/token_bucket.hpp      ядро: Limiter, Bucket, Decision (без зависимости от Python)
src/cpp/bindings.cpp          pybind11-модуль fastbucket._core
src/fastbucket/_pure.py       эталонная реализация на чистом Python
src/fastbucket/asgi.py        RateLimitMiddleware, Stats
src/fastbucket/service/       демо-сервис на FastAPI
tests/                        pytest + hypothesis
benchmarks/                   pytest-benchmark и скрипт для потоков
```

## Ограничения и планы

- **Лимитер живёт внутри процесса.** У каждого воркера `uvicorn --workers N` свой лимитер, поэтому фактический лимит будет в N раз выше. Для нескольких процессов или серверов нужно общее хранилище (в планах Redis).
- **`purge` держит общий мьютекс, пока обходит все бакеты** (около 50 нс на бакет). Это решает шардирование: N словарей с N мьютексами.
- **`X-Forwarded-For` можно подделать.** Включайте `trust_forwarded` только за своим обратным прокси.
- **Планы:** пакетный `consume_many` с отпусканием GIL, шардирование мьютексов, алгоритм sliding window, бэкенд на Redis, сборка колёс через GitHub Actions и cibuildwheel.

## Лицензия

MIT
