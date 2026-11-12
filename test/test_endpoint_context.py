import inspect
import re
from collections.abc import Callable
from typing import Annotated

import pytest
from httpx2 import Response

from clientx import Query
from clientx._endpoint_context import DeprecatedMessage, Endpoint, URLPath
from clientx.decoders import StreamLinesDecoder, StreamResponseDecoder
from clientx.exceptions import (
    EndpointSignatureError,
    MissingDecoderError,
    MissingPathArgumentsError,
    MissingReturnTypeError,
)


def test_endpoint_context_wraps_path_and_extracts_parameters():
    endpoint = Endpoint("GET", "/v1/users/{user_id}")

    assert isinstance(endpoint.path, URLPath)
    assert endpoint.path.path == "/v1/users/{user_id}"
    assert endpoint.path.parameters == ["user_id"]


def test_endpoint_context_requires_func_for_signature():
    endpoint = Endpoint("GET", "/v1/users/{user_id}")

    with pytest.raises(AttributeError, match="_func is not set"):
        _ = endpoint.func

    with pytest.raises(RuntimeError, match="Endpoint.signature is not set"):
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

    def handler(self: object, user_id: str) -> None: ...

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
    endpoint = Endpoint("GET", "/v1/users/{user_id}", decoder=StreamResponseDecoder(), tags=["users"], timeout=30.0)

    def handler(self: object, user_id: str) -> Response: ...

    endpoint.func = handler

    rendered = repr(endpoint)

    assert "Endpoint(method='GET'" in rendered
    assert "path='/v1/users/{user_id}'" in rendered
    assert "tags=['users']" in rendered
    assert "stream=True" in rendered
    assert "timeout=30.0" in rendered
    assert "function='test_endpoint_repr_includes_method_path_function_and_return_type.<locals>.handler'" in rendered
    assert "return_type='Response'" in rendered


def test_endpoint_copies_tags_on_initialization():
    tags = ["one", "two"]

    endpoint = Endpoint("GET", "/v1/users", tags=tags)
    tags.append("mutated")

    assert endpoint.tags == ["one", "two"]


def test_endpoint_repr_works_before_a_function_is_bound():
    rendered = repr(Endpoint("GET", "/v1/items"))

    assert "function=None" in rendered
    assert "return_type=None" in rendered


def test_endpoint_repr_renders_generic_and_union_return_types():
    class User:
        pass

    def list_users(self) -> list[User]: ...

    def find_user(self) -> User | None: ...

    listing = Endpoint("GET", "/v1/users", decoder=lambda response: [])
    listing.func = list_users
    lookup = Endpoint("GET", "/v1/users/me", decoder=lambda response: None)
    lookup.func = find_user

    assert "return_type='list[" in repr(listing)
    assert "User]'" in repr(listing)
    assert "User | None'" in repr(lookup)


def test_endpoint_defaults_stream_to_false():
    endpoint = Endpoint("GET", "/v1/users")

    assert endpoint.stream is False


def test_endpoint_stream_is_decided_by_the_decoder():
    assert Endpoint("GET", "/v1/events", decoder=StreamLinesDecoder()).stream is True
    assert Endpoint("GET", "/v1/download", decoder=StreamResponseDecoder()).stream is True
    assert Endpoint("GET", "/v1/items", decoder=lambda response: response.text).stream is False
    assert Endpoint("GET", "/v1/items").stream is False


def test_endpoint_stream_is_read_only():
    endpoint = Endpoint("GET", "/v1/items")

    with pytest.raises(AttributeError):
        endpoint.stream = True  # type: ignore[misc]


def test_endpoint_defaults_timeout_to_none():
    endpoint = Endpoint("GET", "/v1/users")

    assert endpoint.timeout is None


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


def test_endpoint_parameters_are_analysed_once_when_func_is_set():
    endpoint = Endpoint("GET", "/v1/users/{user_id}")

    def handler(client: object, user_id: str, page: Annotated[int, Query("p")]) -> None: ...

    endpoint.func = handler

    assert endpoint.client_parameter == "client"
    assert list(endpoint.parameters) == ["user_id", "page"]
    assert endpoint.parameters["page"].part == Query("p")


@pytest.mark.parametrize("name", ["client_parameter", "parameters"])
def test_endpoint_parameters_require_func(name: str):
    endpoint = Endpoint("GET", "/v1/users")

    with pytest.raises(RuntimeError, match=f"Endpoint.{name} is not set"):
        getattr(endpoint, name)


def test_endpoint_signature_has_evaluated_annotations():
    endpoint = Endpoint("GET", "/v1/users")

    def handler(self: object, page: "Annotated[int, Query('p')]") -> None: ...

    endpoint.func = handler

    assert endpoint.signature.parameters["page"].annotation == Annotated[int, Query("p")]


def test_a_placeholder_without_a_parameter_raises_when_func_is_set():
    endpoint = Endpoint("GET", "/v1/users/{user_id}/posts/{post_id}")

    def handler(self: object, uid: int, post_id: int) -> None: ...

    with pytest.raises(MissingPathArgumentsError) as info:
        endpoint.func = handler

    assert info.value.missing_args == ["user_id"]
    assert "Missing path arguments for '/v1/users/{user_id}/posts/{post_id}': user_id." in str(info.value)
    assert "needs a parameter for each placeholder in its path" in str(info.value)


def test_a_placeholder_naming_the_client_parameter_raises():
    endpoint = Endpoint("GET", "/v1/{self}")

    def handler(self: object) -> None: ...

    with pytest.raises(MissingPathArgumentsError, match="self"):
        endpoint.func = handler


def test_setting_a_path_after_func_checks_its_placeholders():
    endpoint = Endpoint("GET", "/v1/users")

    def handler(self: object, user_id: int) -> None: ...

    endpoint.func = handler
    endpoint.path = "/v1/users/{user_id}"

    with pytest.raises(MissingPathArgumentsError, match="team_id"):
        endpoint.path = "/v1/teams/{team_id}"


def no_parameters() -> None: ...


def keyword_only_client(*, self: object) -> None: ...


def var_positional_client(*clients: object) -> None: ...


def var_positional(self: object, *ids: int) -> None: ...


def var_keyword(self: object, **filters: str) -> None: ...


@pytest.mark.parametrize(
    ("handler", "problem"),
    [
        (no_parameters, "first, positional parameter"),
        (keyword_only_client, "first, positional parameter"),
        (var_positional_client, "first, positional parameter"),
        (var_positional, "can't take `*ids`"),
        (var_keyword, "can't take `**filters`"),
    ],
    ids=["no parameters", "keyword-only client", "variadic client", "*args", "**kwargs"],
)
def test_a_signature_that_cant_describe_a_request_raises(handler: Callable[..., None], problem: str):
    endpoint = Endpoint("GET", "/v1/users")

    with pytest.raises(EndpointSignatureError, match=re.escape(problem)) as info:
        endpoint.func = handler

    assert info.value.func is handler
    assert f"Endpoint function '{handler.__qualname__}' (defined in test_endpoint_context)" in str(info.value)
