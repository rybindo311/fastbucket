"""Демо-сервис на FastAPI с ограничением запросов через fastbucket.

Запуск:
    uvicorn fastbucket.service.app:create_app --factory
    uvicorn fastbucket.service.app:from_env --factory   # параметры из FASTBUCKET_*
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fastbucket import Limiter
from fastbucket.asgi import RateLimitMiddleware, Stats

EXEMPT = ("/health", "/stats")


def create_app(
        *,
        capacity: float = 10,
        rate: float = 1,
        cost: float = 1.0,
        purge_idle: float = 60,
        purge_interval: float = 30,
        limiter=None,
) -> FastAPI:
    limiter = limiter if limiter is not None else Limiter(capacity, rate)
    stats = Stats()

    async def purge_loop() -> None:
        while True:
            await asyncio.sleep(purge_interval)
            stats.purged += limiter.purge(purge_idle)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(purge_loop())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="fastbucket", lifespan=lifespan)
    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter,
        cost=cost,
        exempt=EXEMPT,
        stats=stats,
    )

    @app.get("/ping")
    async def ping() -> dict:
        return {"pong": True}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/stats")
    async def get_stats() -> dict:
        return {
            "buckets": len(limiter),
            "capacity": limiter.capacity,
            "rate": limiter.rate,
            "cost": cost,
            "allowed": stats.allowed,
            "denied": stats.denied,
            "purged": stats.purged,
        }

    return app


def from_env() -> FastAPI:
    env = os.environ.get
    return create_app(
        capacity=float(env("FASTBUCKET_CAPACITY", "10")),
        rate=float(env("FASTBUCKET_RATE", "1")),
        cost=float(env("FASTBUCKET_COST", "1")),
        purge_idle=float(env("FASTBUCKET_PURGE_IDLE", "60")),
        purge_interval=float(env("FASTBUCKET_PURGE_INTERVAL", "30")),
    )