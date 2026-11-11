"""ASGI-middleware и демо-сервис на FastAPI.

Тесты, принимающие фикстуру limiter_cls, идут на обеих реализациях.
Lifespan (и фоновый purge) работает только внутри `with TestClient(...)`.
"""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastbucket import Limiter, _pure
from fastbucket.asgi import RateLimitMiddleware, Stats
from fastbucket.service.app import create_app, from_env

FROZEN = 1e-9  # пополнение пренебрежимо мало: результаты не зависят от времени


def statuses(client, n, path="/ping", **kwargs):
    return [client.get(path, **kwargs).status_code for _ in range(n)]


def make_app(limiter, **middleware_kwargs) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter, **middleware_kwargs)

    @app.get("/ping")
    async def ping():
        return {"pong": True}

    return app


# --- сервис: лимит, заголовки, тело 429 ------------------------------------------


def test_limit_then_429(limiter_cls):
    with TestClient(create_app(limiter=limiter_cls(2, FROZEN))) as client:
        first, second, third = (client.get("/ping") for _ in range(3))

    assert (first.status_code, second.status_code, third.status_code) == (200, 200, 429)
    assert first.json() == {"pong": True}
    assert (first.headers["x-ratelimit-remaining"], second.headers["x-ratelimit-remaining"]) == ("1", "0")

    body = third.json()
    assert body["detail"] == "rate limit exceeded"
    assert body["retry_after"] > 0


def test_rate_limit_headers_on_allowed_response():
    with TestClient(create_app(capacity=2, rate=1)) as client:
        response = client.get("/ping")

    assert float(response.headers["x-ratelimit-limit"]) == 2
    assert response.headers["x-ratelimit-remaining"] == "1"
    assert response.headers["x-ratelimit-reset"] == "1"  # 1 токен при rate=1/с
    assert "retry-after" not in response.headers


def test_retry_after_is_whole_seconds_rounded_up():
    with TestClient(create_app(capacity=1, rate=1)) as client:
        client.get("/ping")
        denied = client.get("/ping")

    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "1"
    assert 0 < denied.json()["retry_after"] <= 1


def test_api_keys_are_independent():
    with TestClient(create_app(capacity=1, rate=FROZEN)) as client:
        assert statuses(client, 2, headers={"X-API-Key": "alice"}) == [200, 429]
        assert statuses(client, 2, headers={"X-API-Key": "bob"}) == [200, 429]
        assert statuses(client, 2) == [200, 429]  # без ключа — лимит по IP


def test_api_key_cannot_spend_ip_bucket():
    # Префиксы "key:" и "ip:" не дают клиенту выдать себя за чужой IP.
    with TestClient(create_app(capacity=1, rate=FROZEN)) as client:
        assert statuses(client, 1, headers={"X-API-Key": "testclient"}) == [200]
        assert statuses(client, 1) == [200]


def test_empty_api_key_falls_back_to_ip():
    with TestClient(create_app(capacity=1, rate=FROZEN)) as client:
        assert statuses(client, 1) == [200]
        assert statuses(client, 1, headers={"X-API-Key": ""}) == [429]


# --- исключённые пути и /stats ---------------------------------------------------


def test_exempt_paths_are_not_limited_or_counted():
    with TestClient(create_app(capacity=1, rate=FROZEN)) as client:
        assert statuses(client, 5, "/health") == [200] * 5
        assert statuses(client, 5, "/stats") == [200] * 5
        response = client.get("/health")
        stats = client.get("/stats").json()

    assert not any(name.startswith("x-ratelimit") for name in response.headers)
    assert (stats["allowed"], stats["denied"], stats["buckets"]) == (0, 0, 0)


def test_stats_counts_requests_and_hides_keys():
    with TestClient(create_app(capacity=2, rate=FROZEN)) as client:
        statuses(client, 3, headers={"X-API-Key": "secret-123"})
        response = client.get("/stats")

    assert response.json() == {
        "buckets": 1,
        "capacity": 2.0,
        "rate": FROZEN,
        "cost": 1.0,
        "allowed": 2,
        "denied": 1,
        "purged": 0,
    }
    assert "secret-123" not in response.text


def test_cost_is_applied_per_request():
    with TestClient(create_app(capacity=3, rate=FROZEN, cost=2)) as client:
        assert statuses(client, 2) == [200, 429]


# --- фоновый purge и lifespan ----------------------------------------------------


def test_background_purge_removes_idle_full_buckets():
    # rate=1000/с: бакет снова полный через 1 мс, idle=0 — можно удалять сразу.
    app = create_app(limiter=_pure.Limiter(1, 1000), purge_idle=0, purge_interval=0.01)
    with TestClient(app) as client:
        client.get("/ping")
        deadline = time.monotonic() + 2
        while client.get("/stats").json()["purged"] == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        stats = client.get("/stats").json()

    assert stats["purged"] >= 1
    assert stats["buckets"] == 0


def test_background_purge_keeps_drained_buckets():
    app = create_app(capacity=1, rate=FROZEN, purge_idle=0, purge_interval=0.01)
    with TestClient(app) as client:
        client.get("/ping")
        time.sleep(0.1)
        stats = client.get("/stats").json()
        assert client.get("/ping").status_code == 429  # лимит не сброшен очисткой

    assert (stats["purged"], stats["buckets"]) == (0, 1)


def test_app_starts_and_stops_cleanly():
    app = create_app(purge_interval=0.01)
    for _ in range(3):
        with TestClient(app) as client:
            assert client.get("/health").json() == {"status": "ok"}


def test_from_env(monkeypatch):
    monkeypatch.setenv("FASTBUCKET_CAPACITY", "7")
    monkeypatch.setenv("FASTBUCKET_RATE", "0.5")
    monkeypatch.setenv("FASTBUCKET_COST", "2")
    with TestClient(from_env()) as client:
        stats = client.get("/stats").json()

    assert (stats["capacity"], stats["rate"], stats["cost"]) == (7.0, 0.5, 2.0)


# --- RateLimitMiddleware напрямую ------------------------------------------------


def test_forwarded_for_is_ignored_by_default():
    app = make_app(Limiter(1, FROZEN))
    with TestClient(app) as client:
        assert statuses(client, 1, headers={"X-Forwarded-For": "1.1.1.1"}) == [200]
        assert statuses(client, 1, headers={"X-Forwarded-For": "2.2.2.2"}) == [429]


def test_forwarded_for_uses_first_address_when_trusted():
    app = make_app(Limiter(1, FROZEN), trust_forwarded=True)
    with TestClient(app) as client:
        assert statuses(client, 1, headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"}) == [200]
        assert statuses(client, 1, headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.2"}) == [429]
        assert statuses(client, 1, headers={"X-Forwarded-For": "2.2.2.2"}) == [200]


def test_custom_key_func():
    app = make_app(Limiter(1, FROZEN), key_func=lambda scope: "everyone")
    with TestClient(app) as client:
        assert statuses(client, 1, headers={"X-API-Key": "a"}) == [200]
        assert statuses(client, 1, headers={"X-API-Key": "b"}) == [429]


def test_stats_object_is_optional_and_shared():
    stats = Stats()
    with TestClient(make_app(Limiter(1, FROZEN), stats=stats)) as client:
        statuses(client, 3)
    assert (stats.allowed, stats.denied) == (1, 2)

    with TestClient(make_app(Limiter(1, FROZEN))) as client:  # без stats
        assert statuses(client, 2) == [200, 429]


@pytest.mark.parametrize("cost", [0, -1, 3, float("nan")])
def test_invalid_cost_fails_at_startup(cost):
    app = make_app(Limiter(2, 1), cost=cost)
    with pytest.raises(ValueError, match="cost"):
        with TestClient(app):
            pass
