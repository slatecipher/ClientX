import pytest

from clientx import method
from clientx._decorators import ApiMethod


@pytest.mark.parametrize("name", ["get", "post", "put", "patch", "delete", "head", "options"])
def test_each_decorator_sends_its_http_method(name: str):
    decorator = getattr(method, name)

    assert isinstance(decorator, ApiMethod)
    assert decorator.method == name.upper()
