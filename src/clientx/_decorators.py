from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar, cast, overload

import httpx2

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


class RawEndpointDecorator(Protocol):
    """Decorator returned by an HTTP verb call without ``decoder=``, e.g. ``get("/users")``.

    The decorated method must return ``httpx2.Response`` or ``None``; any other
    return type needs a decoder. Type checkers report the mismatch at the
    decorator, and ClientX raises ``MissingDecoderError`` when the class is defined.

    Spelling the decorator types out (instead of a bare ``Callable``) keeps each
    decorated method's parameters and return type visible to type checkers. With
    a bare ``Callable``, mypy sees every endpoint as ``Any``.
    """

    def __call__[C: ClientX, **Q, S: (httpx2.Response, None)](
        self, func: Callable[Concatenate[C, Q], S], /
    ) -> Callable[Concatenate[C, Q], S]:
        """Register ``func`` as an endpoint and return its request-sending replacement."""
        ...


class DecodedEndpointDecorator[D](Protocol):
    """Decorator returned by an HTTP verb call with ``decoder=``.

    ``D`` is the decoder's output type. Callers of the decorated method see
    that type, and the method's declared return type must be the same or
    narrower: ``decoder=ModelDecoder(User)`` fits ``-> User`` but not ``-> str``.

    The ``self`` annotation on ``__call__`` binds ``S`` to the decoder output
    before the method is checked against it. Decoders returning ``Any`` (such as
    ``json_decoder``) accept any annotation; pyright then reports the call result
    as ``Any`` while mypy keeps the annotation.
    """

    def __call__[C: ClientX, **Q, S](
        self: "DecodedEndpointDecorator[S]", func: Callable[Concatenate[C, Q], S], /
    ) -> Callable[Concatenate[C, Q], S]:
        """Register ``func`` as an endpoint and return its request-sending replacement."""
        ...


@dataclass(frozen=True)
class ApiMethod:
    method: MethodType

    @overload
    def __call__[D](
        self,
        path: str,
        *,
        decoder: Callable[[httpx2.Response], D],
        deprecated: DeprecatedType | None = None,
        tags: list[str] | None = None,
        stream: bool | None = None,
        timeout: httpx2.Timeout | float | None = None,
    ) -> DecodedEndpointDecorator[D]: ...

    @overload
    def __call__(
        self,
        path: str,
        *,
        decoder: None = None,
        deprecated: DeprecatedType | None = None,
        tags: list[str] | None = None,
        stream: bool | None = None,
        timeout: httpx2.Timeout | float | None = None,
    ) -> RawEndpointDecorator: ...

    def __call__(
        self,
        path: str,
        *,
        decoder: Decoder | None = None,
        deprecated: DeprecatedType | None = None,
        tags: list[str] | None = None,
        stream: bool | None = None,
        timeout: httpx2.Timeout | float | None = None,
    ) -> DecodedEndpointDecorator[Any] | RawEndpointDecorator:
        """Build a decorator that registers an endpoint for this HTTP method.

        Args:
            path: URL path template for the endpoint (e.g., ``/v1/users/{user_id}``).
            decoder: Optional response decoder used when the endpoint's return
                type is neither ``httpx2.Response`` nor ``None``.
            deprecated: Optional deprecation metadata or callable that emits a
                warning when the endpoint is invoked.
            tags: Optional metadata labels attached to the endpoint for
                registry filtering and sorting. Defaults to None.
            stream: Whether to send the request in streamed mode. When ``None``
                (the default), follows the decoder's ``stream`` attribute, so
                stream decoders stream automatically; otherwise False.
            timeout: Optional timeout override applied to requests sent to this
                endpoint. Defaults to None.

        Returns:
            A decorator that wraps and registers the endpoint. Its type ties the
            decorated method's return annotation to ``decoder``.
        """

        def decorator(
            func: Callable[Concatenate[T, P], R],
        ) -> Callable[Concatenate[T, P], R]:
            endpoint = Endpoint(
                method=self.method,
                path=path,
                decoder=decoder,
                deprecated=deprecated,
                tags=tags,
                stream=stream,
                timeout=timeout,
            )
            request_factory = RequestFactory(endpoint)

            @wraps(func)
            def wrapper(_self: T, *args: P.args, **kwargs: P.kwargs) -> R:
                endpoint.check_deprecation()

                spec = request_factory(arguments=endpoint.bind(_self, args, kwargs))

                if endpoint.timeout is not None:
                    spec.parts.setdefault("timeout", endpoint.timeout)

                response = _self.send(
                    method=endpoint.method,
                    path=spec.path,
                    stream=endpoint.stream,
                    **spec.parts,
                )

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
