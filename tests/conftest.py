import pytest

import fastbucket
from fastbucket import _pure

IMPLEMENTATIONS = {
    "cpp": fastbucket.Limiter,
    "pure": _pure.Limiter,
}


@pytest.fixture(params=sorted(IMPLEMENTATIONS))
def limiter_cls(request):
    """Класс Limiter: каждый тест с этой фикстурой запускается на обеих реализациях."""
    return IMPLEMENTATIONS[request.param]
