import pytest

import fastbucket
from fastbucket import _pure

IMPLEMENTATIONS = {
    "cpp": fastbucket.Limiter,
    "pure": _pure.Limiter,
}


@pytest.fixture(params=sorted(IMPLEMENTATIONS))
def limiter_cls(request):
    return IMPLEMENTATIONS[request.param]
