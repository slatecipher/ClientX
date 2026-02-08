import inspect

import pytest
from httpx import Response

from clientx._endpoint_context import DeprecatedMessage, Endpoint, EndpointRegister, URLPath
from clientx.exceptions import MissingDecoderError, MissingPathArgumentsError, MissingReturnTypeError


def test_endpoint_context_wraps_path_and_extracts_parameters():
    endpoint = Endpoint("GET", "/v1/users/{user_id}")

    assert isinstance(endpoint.path, URLPath)
    assert endpoint.path.path == "/v1/users/{user_id}"
    assert endpoint.path.parameters == ["user_id"]


def test_endpoint_context_requires_func_for_signature():
    endpoint = Endpoint("GET", "/v1/users/{user_id}")

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
    endpoint = Endpoint("GET", "/v1/users/{user_id}")

    def handler(user_id: str) -> None: ...

    endpoint.func = handler

    assert endpoint.signature == inspect.signature(handler)


def test_endpoint_context_path_setter_wraps_url_path():
    endpoint = Endpoint("GET", "/v1/users/{user_id}")

    endpoint.path = "/v1/teams/{team_id}"

    assert isinstance(endpoint.path, URLPath)
    assert str(endpoint.path) == "/v1/teams/{team_id}"


def test_deprecated_emits_deprecation_warning():
    deprecated = DeprecatedMessage("Use /v2/users instead.")

    with pytest.warns(DeprecationWarning, match="Use /v2/users instead."):
        deprecated()


def test_endpoint_repr_includes_method_path_function_and_return_type():
    endpoint = Endpoint("GET", "/v1/users/{user_id}")

    def handler(user_id: str) -> Response: ...

    endpoint.func = handler

    rendered = repr(endpoint)

    assert "Endpoint(method='GET'" in rendered
    assert "path='/v1/users/{user_id}'" in rendered
    assert "function='test_endpoint_repr_includes_method_path_function_and_return_type.<locals>.handler'" in rendered
    assert "return_type='Response'" in rendered


def test_endpoint_check_deprecation_calls_callable():
    endpoint = Endpoint("GET", "/v1/users")
    calls = {"count": 0}

    def deprecated_call() -> None:
        calls["count"] += 1

    endpoint.deprecated = deprecated_call
    endpoint.check_deprecation()

    assert calls["count"] == 1


def test_endpoint_func_requires_decoder_for_decodable_return_type():
    endpoint = Endpoint("GET", "/v1/users")

    def handler() -> int: ...

    with pytest.raises(MissingDecoderError):
        endpoint.func = handler


def test_endpoint_func_requires_return_annotation():
    endpoint = Endpoint("GET", "/v1/users")

    def handler(): ...

    with pytest.raises(MissingReturnTypeError):
        endpoint.func = handler


def test_endpoint_register_appends_endpoint():
    endpoint = Endpoint("GET", "/v1/users")
    original = list(EndpointRegister.registry)
    try:
        EndpointRegister.register(endpoint)
        assert EndpointRegister.registry[-1] is endpoint
    finally:
        EndpointRegister.registry = original


def test_endpoint_register_iter_yields_registered_endpoints_in_order():
    first = Endpoint("GET", "/v1/users")
    second = Endpoint("POST", "/v1/users")
    original = list(EndpointRegister.registry)
    try:
        EndpointRegister.registry = [first, second]

        endpoints = list(EndpointRegister.iter())

        assert endpoints == [first, second]
        assert endpoints[0] is first
        assert endpoints[1] is second
    finally:
        EndpointRegister.registry = original
