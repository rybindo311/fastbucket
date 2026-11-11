"""fastbucket — in-process token bucket rate limiter with a C++ core."""

from ._core import Decision, Limiter, __version__

__all__ = ["Decision", "Limiter", "__version__"]