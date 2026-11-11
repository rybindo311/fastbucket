import json
from dataclasses import dataclass
from math import floor, ceil
from typing import Iterable
from collections.abc import Callable


@dataclass
class Stats:
    allowed: int = 0
    denied: int = 0


def get_header(scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return value.decode("latin-1")
    return None


async def send_json(send, status, payload, headers=()):
    body = json.dumps(payload).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            *headers,
        ],
    })
    await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware:
    def __init__(
            self,
            app,
            *,
            limiter,
            cost: float | int = 1.0,
            exempt: Iterable[str] = (),
            trust_forwarded: bool = False,
            key_func: Callable[[dict], str] | None = None,
            stats: Stats | None = None,
    ):
        self.app = app
        if not (0 < cost <= limiter.capacity):
            raise ValueError(f"cost must be in (0, {limiter.capacity}]")
        self._limiter = limiter
        self._cost = float(cost)
        self._exempt = frozenset(exempt)
        self._trust_forwarded = trust_forwarded
        self._key_func = key_func
        self._stats = stats

    def _key(self, scope) -> str:
        if self._key_func is not None:
            return self._key_func(scope)
        if key := get_header(scope, b"x-api-key"):
            return f"key: {key}"
        if self._trust_forwarded and (value := get_header(scope, b"x-forwarded-for")):
            ip = value.split(",")[0].strip()
            return f"ip: {ip}"
        if client := scope.get("client"):
            return f"ip: {client[0]}"
        return "anon"

    def _headers(self, decision) -> list[tuple[bytes, bytes]]:
        remaining = floor(decision.remaining)
        reset = ceil((self._limiter.capacity - decision.remaining) / self._limiter.rate)
        capacity = self._limiter.capacity
        headers = [
            (b"x-ratelimit-remaining", str(remaining).encode("ascii")),
            (b"x-ratelimit-reset", str(reset).encode("ascii")),
            (b"x-ratelimit-limit", str(capacity).encode("ascii"))
        ]
        if not decision.allowed:
            headers.append(
                (b"retry-after", str(ceil(decision.retry_after)).encode("ascii"))
            )
        return headers

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in self._exempt:
            await self.app(scope, receive, send)
            return
        decision = self._limiter.consume(self._key(scope), self._cost)

        if not decision.allowed:
            if self._stats is not None:
                self._stats.denied += 1

            await send_json(
                send,
                429,
                {
                    "detail": "rate limit exceeded",
                    "retry_after": decision.retry_after,
                },
                headers=self._headers(decision),
            )
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *self._headers(decision)]
            await send(message)

        if self._stats is not None:
            self._stats.allowed += 1

        await self.app(scope, receive, send_wrapper)