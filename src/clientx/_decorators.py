import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from functools import wraps
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar, cast, overload

import httpx2

from clientx._client import ClientX, Resource, client_of, send_request
from clientx._client_types import (
    Decoder,
    DeprecatedType,
    MethodType,
    is_none_type,
    is_response_type,
)
from clientx._endpoint_context import Endpoint
from clientx._logging import EndpointCall, log_endpoint_call
from clientx._registry import register_endpoint_function
from clientx._request_factory import RequestFactory
from clientx.decoders import StreamDecoder

P = ParamSpec("P")
T = TypeVar("T", bound=ClientX | Resource)
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

    def __call__[C: ClientX | Resource, **Q, S: (httpx2.Response, None)](
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

    def __call__[C: ClientX | Resource, **Q, S](
        self: "DecodedEndpointDecorator[S]", func: Callable[Concatenate[C, Q], S], /
    ) -> Callable[Concatenate[C, Q], S]:
        """Register ``func`` as an endpoint and return its request-sending replacement."""
        ...


def _raises_for_status(endpoint: Endpoint, client: ClientX) -> bool:
    """Whether ``endpoint`` checks the status code: its own setting if it has one (``True`` or
    ``False``), or else the client's. Not ``any()``: an endpoint's ``False`` must win over the client's ``True``.
    """
    return client.__clientx_raise_for_status__ if endpoint.raise_for_status is None else endpoint.raise_for_status


def _validates_arguments(endpoint: Endpoint, client: ClientX) -> bool:
    """Whether ``endpoint`` checks its arguments: its own setting if it has one, or else the client's."""
    if endpoint.validate_arguments is None:
        return client.__clientx_validate_arguments__
    return endpoint.validate_arguments


def _raise_status_error(response: httpx2.Response) -> None:
    """Raise ``httpx2.HTTPStatusError`` for ``response``, which must be a 4xx or 5xx.

    The caller checks ``response.is_error`` first: called on a 3xx this would raise, and
    on a successful streamed response it would read the body the decoder should stream.
    The body is read, so the error keeps it, and the response is closed, so a streamed
    one releases its connection. For a response that isn't streamed, httpx2 has already
    done both, and they do nothing.
    """
    try:
        response.read()
    finally:
        response.close()
    response.raise_for_status()


def _decode(decoder: Decoder, response: httpx2.Response) -> object:
    """Run ``decoder`` on ``response``, making sure a streamed response gets closed.

    - ``StreamDecoder``: the response is streamed. Close it if the decoder raises,
      and wrap its iterator so the response closes when iteration finishes, stops
      early, or fails.
    - ``StreamResponseDecoder``: the response is streamed and handed to the caller,
      who owns it.
    - Any other decoder: httpx2 already read and closed the body, so decode directly.
    """
    if not isinstance(decoder, StreamDecoder):
        return decoder(response)

    try:
        items = cast(StreamDecoder[object], decoder)(response)
    except BaseException:
        response.close()
        raise
    return _close_when_done(items, response)


def _close_when_done[T](items: Iterable[T], response: httpx2.Response) -> Iterator[T]:
    """Yield from ``items``, then close ``response`` however iteration ends.

    The finally block runs on exhaustion, on an exception, and when the generator is
    closed (explicitly, or by a ``for`` loop that breaks early). An iterator that is
    never started or is kept alive stays open until it is closed or garbage-collected.
    """
    try:
        yield from items
    finally:
        response.close()


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
        timeout: httpx2.Timeout | float | None = None,
        raise_for_status: bool | None = None,
        validate_arguments: bool | None = None,
    ) -> DecodedEndpointDecorator[D]: ...

    @overload
    def __call__(
        self,
        path: str,
        *,
        decoder: None = None,
        deprecated: DeprecatedType | None = None,
        tags: list[str] | None = None,
        timeout: httpx2.Timeout | float | None = None,
        raise_for_status: bool | None = None,
        validate_arguments: bool | None = None,
    ) -> RawEndpointDecorator: ...

    def __call__(
        self,
        path: str,
        *,
        decoder: Decoder | None = None,
        deprecated: DeprecatedType | None = None,
        tags: list[str] | None = None,
        timeout: httpx2.Timeout | float | None = None,
        raise_for_status: bool | None = None,
        validate_arguments: bool | None = None,
    ) -> DecodedEndpointDecorator[Any] | RawEndpointDecorator:
        """Build a decorator that registers an endpoint for this HTTP method.

        Args:
            path: URL path template for the endpoint (e.g., ``/v1/users/{user_id}``).
            decoder: Response decoder. Required when the endpoint's return type is
                neither ``httpx2.Response`` nor ``None``. It also decides streaming:
                ``StreamDecoder`` subclasses and ``StreamResponseDecoder`` send the
                request in streaming mode.
            deprecated: Optional deprecation metadata or callable that emits a
                warning when the endpoint is invoked.
            tags: Optional metadata labels attached to the endpoint, which
                ``clientx.tools.list_tools`` can filter by. Defaults to None.
            timeout: Optional timeout override applied to requests sent to this
                endpoint. Defaults to None.
            raise_for_status: Whether a 4xx or 5xx response raises
                ``httpx2.HTTPStatusError`` before the decoder runs. ``None`` (the
                default) follows the client's ``raise_for_status``, which is on
                unless the client turns it off.
            validate_arguments: Whether each argument is checked against its
                parameter's annotation before the request is sent, raising
                ``ArgumentValidationError`` if it doesn't match. ``None`` (the
                default) follows the client's ``validate_arguments``, which is off
                unless the client turns it on.

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
                timeout=timeout,
                raise_for_status=raise_for_status,
                validate_arguments=validate_arguments,
            )
            request_factory = RequestFactory(endpoint)
            endpoint_name = func.__qualname__

            @wraps(func)
            # `_self` is positional-only, like the first parameter `Concatenate` describes.
            def wrapper(_self: T, /, *args: P.args, **kwargs: P.kwargs) -> R:
                # The client whose connection sends the request; `_self` may be a mounted resource.
                client = client_of(_self)
                endpoint.check_deprecation()

                arguments = endpoint.bind(_self, args, kwargs, validate=_validates_arguments(endpoint, client))
                spec = request_factory(arguments=arguments)

                # Taken before `timeout` is added: it's a request option, not a request part.
                call = EndpointCall(
                    endpoint=endpoint_name,
                    method=endpoint.method,
                    path=spec.path,
                    parts=tuple(str(part) for part in spec.parts),
                    stream=endpoint.stream,
                )

                if endpoint.timeout is not None:
                    spec.parts.setdefault("timeout", endpoint.timeout)

                started = time.perf_counter()
                try:
                    response = send_request(
                        client,
                        method=endpoint.method,
                        path=spec.path,
                        stream=endpoint.stream,
                        **spec.parts,
                    )
                except Exception as error:
                    log_endpoint_call(call, started=started, error=error)
                    raise

                if response.is_error and _raises_for_status(endpoint, client):
                    try:
                        _raise_status_error(response)
                    except Exception as error:
                        log_endpoint_call(call, started=started, status=response.status_code, error=error)
                        raise
                log_endpoint_call(call, started=started, status=response.status_code)

                # A decoder, when given, always runs, whatever the return annotation.
                if decoder is not None:
                    return cast(R, _decode(decoder, response))

                if is_none_type(endpoint.return_type):
                    return cast(R, None)

                if is_response_type(endpoint.return_type):
                    return cast(R, response)

                raise RuntimeError("Internal error: decoder was None for a decodable return type.")

            endpoint.func = wrapper
            register_endpoint_function(wrapper, endpoint)
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
