from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Concatenate, ParamSpec, TypeVar, cast

import httpx

from clientx.call_context import CallContext
from clientx.client import ClientX
from clientx.client_types import (
    Decoder,
    DeprecatedType,
    MethodType,
    is_none_type,
    is_response_type,
)
from clientx.endpoint_context import (
    EndpointContext,
    EndpointsRegister,
)
from clientx.request_factory import RequestFactory

endpoints = EndpointsRegister.default()


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
            _endpoint = EndpointContext(method=self.method, path=path, decoder=decoder, deprecated=deprecated)
            _request_factory = RequestFactory()

            @wraps(func)
            def wrapper(_self: T, *args: P.args, **kwargs: P.kwargs) -> R:
                _endpoint.check_deprecation()

                call_ctx = CallContext.from_call(endpoint=_endpoint, client=_self, args=args, kwargs=kwargs)

                request = _request_factory(call_ctx)

                response: httpx.Response = call_ctx.client.send(method=call_ctx.method, **request)

                if is_none_type(call_ctx.return_type):
                    return cast(R, None)

                if is_response_type(call_ctx.return_type):
                    return cast(R, response)

                if decoder is None:
                    raise RuntimeError("Internal error: decoder was None for a decodable return type.")

                return cast(R, decoder(response))

            _endpoint.func = wrapper
            endpoints.register(_endpoint)
            return wrapper

        return decorator


@dataclass(frozen=True)
class Api:
    """Container for HTTP verb decorators."""

    delete: ApiMethod
    """DELETE request decorator."""
    get: ApiMethod
    """GET request decorator."""
    head: ApiMethod
    """HEAD request decorator."""
    options: ApiMethod
    """OPTIONS request decorator."""
    patch: ApiMethod
    """PATCH request decorator."""
    post: ApiMethod
    """POST request decorator."""
    put: ApiMethod
    """PUT request decorator."""


# Preconfigured HTTP verb decorators for client usage.
api = Api(
    delete=ApiMethod("DELETE"),
    get=ApiMethod("GET"),
    head=ApiMethod("HEAD"),
    options=ApiMethod("OPTIONS"),
    patch=ApiMethod("PATCH"),
    post=ApiMethod("POST"),
    put=ApiMethod("PUT"),
)

__all__ = ["api", "endpoints"]
