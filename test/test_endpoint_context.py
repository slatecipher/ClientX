import inspect

import pytest

from clientx.endpoint_context import Deprecated, EndpointContext, URLPath
from clientx.exceptions import MissingPathArgumentsError


def test_endpoint_context_wraps_path_and_extracts_parameters():
    endpoint = EndpointContext("GET", "/v1/users/{user_id}")

    assert isinstance(endpoint.path, URLPath)
    assert endpoint.path.path == "/v1/users/{user_id}"
    assert endpoint.path.parameters == ["user_id"]


def test_endpoint_context_requires_func_for_signature():
    endpoint = EndpointContext("GET", "/v1/users/{user_id}")

    with pytest.raises(AttributeError, match="_func is not set"):
        _ = endpoint.func

    with pytest.raises(RuntimeError, match="EndpointContext.signature is not set"):
        _ = endpoint.signature


def test_url_path_format_fills_parameters():
    path = URLPath("/v1/users/{user_id}/posts/{post_id}")

    formatted = path.format({"user_id": "42", "post_id": "abc"})

    assert formatted == "/v1/users/42/posts/abc"


def test_url_path_format_requires_all_parameters():
    path = URLPath("/v1/users/{user_id}/posts/{post_id}")

    with pytest.raises(
        MissingPathArgumentsError, match=("Missing path arguments for '/v1/users/{user_id}/posts/{post_id}': post_id")
    ):
        path.format({"user_id": "42"})


def test_url_path_str_returns_template():
    path = URLPath("/v1/users/{user_id}")

    assert str(path) == "/v1/users/{user_id}"


def test_endpoint_context_signature_is_set_with_func():
    endpoint = EndpointContext("GET", "/v1/users/{user_id}")

    def handler(user_id: str) -> None: ...

    endpoint.func = handler

    assert endpoint.signature == inspect.signature(handler)


def test_endpoint_context_path_setter_wraps_url_path():
    endpoint = EndpointContext("GET", "/v1/users/{user_id}")

    endpoint.path = "/v1/teams/{team_id}"

    assert isinstance(endpoint.path, URLPath)
    assert str(endpoint.path) == "/v1/teams/{team_id}"


def test_deprecated_emits_deprecation_warning():
    deprecated = Deprecated("Use /v2/users instead.")

    with pytest.warns(DeprecationWarning, match="Use /v2/users instead."):
        deprecated()
