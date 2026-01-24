from dataclasses import dataclass
from functools import wraps
from typing import Callable, Concatenate, ParamSpec, TypeVar, cast

import httpx

from clientx.call_context import CallContext
from clientx.client import ClientX
from clientx.client_types import (
    Decoder,
    MethodType,
    is_none_type,
    is_response_type,
)
from clientx.endpoint_context import (
    EndpointContext,
    EndpointRegistry,
)
from clientx.request_factory import RequestFactory

endpoint_registry = EndpointRegistry.default()


P = ParamSpec("P")
T = TypeVar("T", bound=ClientX)
R = TypeVar("R")


@dataclass(frozen=True)
class ApiMethod:
    method: MethodType

    def __call__(
        self,
        path: str,
        *,
        decoder: Decoder | None = None,
    ):
        def decorator(
            func: Callable[Concatenate[T, P], R],
        ) -> Callable[Concatenate[T, P], R]:
            endpoint = EndpointContext(method=self.method, path=path, decoder=decoder)
            request_factory = RequestFactory()

            @wraps(func)
            def wrapper(_self: T, *args: P.args, **kwargs: P.kwargs) -> R:
                call_ctx = CallContext.from_call(endpoint=endpoint, client=_self, args=args, kwargs=kwargs)

                request = request_factory(call_ctx)

                response: httpx.Response = call_ctx.client.send(method=call_ctx.endpoint.method, **request)

                if is_none_type(endpoint.return_type):
                    return cast(R, None)

                if is_response_type(endpoint.return_type):
                    return cast(R, response)

                assert decoder is not None

                return cast(R, decoder(response))

            endpoint.func = wrapper
            endpoint_registry.register(endpoint)
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


api = Api(
    delete=ApiMethod("DELETE"),
    get=ApiMethod("GET"),
    head=ApiMethod("HEAD"),
    options=ApiMethod("OPTIONS"),
    patch=ApiMethod("PATCH"),
    post=ApiMethod("POST"),
    put=ApiMethod("PUT"),
)
