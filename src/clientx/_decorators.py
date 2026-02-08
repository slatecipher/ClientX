from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Concatenate, ParamSpec, TypeVar, cast

import httpx

from clientx._client import ClientX
from clientx._client_types import (
    Decoder,
    DeprecatedType,
    MethodType,
    is_none_type,
    is_response_type,
)
from clientx._endpoint_context import (
    Endpoint,
    EndpointRegister,
)
from clientx._request_factory import RequestFactory

P = ParamSpec("P")
T = TypeVar("T", bound=ClientX)
R = TypeVar("R")


@dataclass(frozen=True)
class ApiMethod:
    method: MethodType

    def __call__(
        self, path: str, *, decoder: Decoder | None = None, deprecated: DeprecatedType | None = None
    ) -> Callable:
        """Build a decorator that registers an endpoint for this HTTP method.

        Args:
            path: URL path template for the endpoint (e.g., ``/v1/users/{user_id}``).
            decoder: Optional response decoder used when the endpoint's return
                type is neither ``httpx.Response`` nor ``None``.
            deprecated: Optional deprecation metadata or callable that emits a
                warning when the endpoint is invoked.

        Returns:
            Callable: A decorator that wraps and registers the endpoint.
        """

        def decorator(
            func: Callable[Concatenate[T, P], R],
        ) -> Callable[Concatenate[T, P], R]:
            endpoint = Endpoint(method=self.method, path=path, decoder=decoder, deprecated=deprecated)
            request_factory = RequestFactory(endpoint)

            @wraps(func)
            def wrapper(_self: T, *args: P.args, **kwargs: P.kwargs) -> R:
                endpoint.check_deprecation()

                request = request_factory(arguments=endpoint.bind(_self, args, kwargs))

                response: httpx.Response = _self.send(method=endpoint.method, **request)

                if is_none_type(endpoint.return_type):
                    return cast(R, None)

                if is_response_type(endpoint.return_type):
                    return cast(R, response)

                if decoder is None:
                    raise RuntimeError("Internal error: decoder was None for a decodable return type.")

                return cast(R, decoder(response))

            endpoint.func = wrapper
            EndpointRegister.register(endpoint)
            return wrapper

        return decorator


@dataclass(frozen=True)
class MethodContainer:
    """Container for HTTP verb decorators.

    Attributes:
        delete: DELETE request decorator.
        get: GET request decorator.
        head: HEAD request decorator.
        options: OPTIONS request decorator.
        patch: PATCH request decorator.
        post: POST request decorator.
        put: PUT request decorator.
    """

    delete: ApiMethod
    get: ApiMethod
    head: ApiMethod
    options: ApiMethod
    patch: ApiMethod
    post: ApiMethod
    put: ApiMethod


# Preconfigured HTTP verb decorators for client usage.
method = MethodContainer(
    delete=ApiMethod("DELETE"),
    get=ApiMethod("GET"),
    head=ApiMethod("HEAD"),
    options=ApiMethod("OPTIONS"),
    patch=ApiMethod("PATCH"),
    post=ApiMethod("POST"),
    put=ApiMethod("PUT"),
)
