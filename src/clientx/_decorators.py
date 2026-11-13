import inspect
import time
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Callable, Coroutine, Iterable, Iterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import wraps
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar, cast, overload

import httpx2

from clientx._client import (
    AsyncClientX,
    AsyncResource,
    ClientX,
    Resource,
    asend_request,
    async_client_of,
    client_of,
    send_request,
)
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
from clientx._request_factory import RequestFactory, RequestSpec
from clientx.decoders import AsyncStreamDecoder, StreamDecoder

P = ParamSpec("P")
T = TypeVar("T", bound=ClientX | AsyncClientX | Resource | AsyncResource)
R = TypeVar("R")


# Each decorator protocol has three overloads: `def` methods of a ClientX or Resource, `async def` methods of
# an AsyncClientX or AsyncResource, then the `def` overload again.
# - Limiting each overload to its own kind of class means only one can match a method, even when its types
#   involve `Any` (an `-> Any` annotation, or `json_decoder`). If two matched, mypy would treat the endpoint
#   as untyped. That's why async resources are a separate class.
# - When a method fits none of them, mypy reports the first overload's error and pyright the last's. With the
#   `def` overload in both places, both explain a mistake in a `def` endpoint the way they did before async
#   support. The repeated overload never changes which one matches.
class RawEndpointDecorator(Protocol):
    """Decorator returned by an HTTP verb call without ``decoder=``, e.g. ``get("/users")``.

    The decorated method must return ``httpx2.Response`` or ``None`` (or, for an
    ``async def`` method, return them when awaited); any other return type needs a
    decoder. Type checkers report the mismatch at the decorator, and ClientX raises
    ``MissingDecoderError`` when the class is defined.

    Spelling the decorator types out (instead of a bare ``Callable``) keeps each
    decorated method's parameters and return type visible to type checkers. With
    a bare ``Callable``, mypy sees every endpoint as ``Any``.
    """

    @overload
    def __call__[C: ClientX | Resource, **Q, ResponseOrNone: (httpx2.Response, None)](
        self, func: Callable[Concatenate[C, Q], ResponseOrNone], /
    ) -> Callable[Concatenate[C, Q], ResponseOrNone]: ...

    @overload
    def __call__[C: AsyncClientX | AsyncResource, **Q, ResponseOrNone: (httpx2.Response, None)](
        self, func: Callable[Concatenate[C, Q], Coroutine[Any, Any, ResponseOrNone]], /
    ) -> Callable[Concatenate[C, Q], Coroutine[Any, Any, ResponseOrNone]]: ...

    @overload
    def __call__[C: ClientX | Resource, **Q, ResponseOrNone: (httpx2.Response, None)](
        self, func: Callable[Concatenate[C, Q], ResponseOrNone], /
    ) -> Callable[Concatenate[C, Q], ResponseOrNone]: ...

    def __call__(self, func: Callable[..., Any], /) -> Callable[..., Any]:
        """Register ``func`` as an endpoint and return its request-sending replacement."""
        ...


class DecodedEndpointDecorator[D](Protocol):
    """Decorator returned by an HTTP verb call with ``decoder=``.

    ``D`` is the decoder's output type. Callers of the decorated method see that
    type (awaited, for an ``async def`` method), and the method's declared return
    type must be the same or narrower: ``decoder=ModelDecoder(User)`` fits
    ``-> User`` but not ``-> str``.

    The ``self`` annotation on ``__call__`` binds ``DecoderOutput`` to the decoder's
    output type before the method is checked against it. Decoders returning ``Any``
    (such as ``json_decoder``) accept any annotation; pyright then reports the call
    result as ``Any`` while mypy keeps the annotation.
    """

    @overload
    def __call__[C: ClientX | Resource, **Q, DecoderOutput](
        self: "DecodedEndpointDecorator[DecoderOutput]", func: Callable[Concatenate[C, Q], DecoderOutput], /
    ) -> Callable[Concatenate[C, Q], DecoderOutput]: ...

    @overload
    def __call__[C: AsyncClientX | AsyncResource, **Q, DecoderOutput](
        self: "DecodedEndpointDecorator[DecoderOutput]",
        func: Callable[Concatenate[C, Q], Coroutine[Any, Any, DecoderOutput]],
        /,
    ) -> Callable[Concatenate[C, Q], Coroutine[Any, Any, DecoderOutput]]: ...

    @overload
    def __call__[C: ClientX | Resource, **Q, DecoderOutput](
        self: "DecodedEndpointDecorator[DecoderOutput]", func: Callable[Concatenate[C, Q], DecoderOutput], /
    ) -> Callable[Concatenate[C, Q], DecoderOutput]: ...

    def __call__(self, func: Callable[..., Any], /) -> Callable[..., Any]:
        """Register ``func`` as an endpoint and return its request-sending replacement."""
        ...


def _raises_for_status(endpoint: Endpoint, client: ClientX | AsyncClientX) -> bool:
    """Whether ``endpoint`` checks the status code: its own setting if it has one (``True`` or
    ``False``), or else the client's. Not ``any()``: an endpoint's ``False`` must win over the client's ``True``.
    """
    return client.__clientx_raise_for_status__ if endpoint.raise_for_status is None else endpoint.raise_for_status


def _validates_arguments(endpoint: Endpoint, client: ClientX | AsyncClientX) -> bool:
    """Whether ``endpoint`` checks its arguments: its own setting if it has one, or else the client's."""
    if endpoint.validate_arguments is None:
        return client.__clientx_validate_arguments__
    return endpoint.validate_arguments


def _prepare(
    endpoint: Endpoint,
    request_factory: RequestFactory,
    name: str,
    *,
    owner: ClientX | AsyncClientX | Resource | AsyncResource,
    client: ClientX | AsyncClientX,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[EndpointCall, RequestSpec]:
    """Do everything a call does before sending: warn if deprecated, bind and check the arguments, build the request.

    Returns the call's log details and the request to send. ``def`` and ``async def`` endpoints share it.
    """
    endpoint.check_deprecation()

    arguments = endpoint.bind(owner, args, kwargs, validate=_validates_arguments(endpoint, client))
    spec = request_factory(arguments=arguments)

    # Taken before `timeout` is added: it's a request option, not a request part.
    call = EndpointCall(
        endpoint=name,
        method=endpoint.method,
        path=spec.path,
        parts=tuple(str(part) for part in spec.parts),
        stream=endpoint.stream,
    )

    if endpoint.timeout is not None:
        spec.parts.setdefault("timeout", endpoint.timeout)
    return call, spec


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


async def _araise_status_error(response: httpx2.Response) -> None:
    """The ``async`` counterpart of ``_raise_status_error``, for responses from an ``httpx2.AsyncClient``."""
    try:
        await response.aread()
    finally:
        await response.aclose()
    response.raise_for_status()


def _result(endpoint: Endpoint, decoder: Decoder | None, response: httpx2.Response) -> object:
    """Return what the call returns: the decoder's output, or else ``None`` or the response, per the annotation."""
    # A decoder, when given, always runs, whatever the return annotation.
    if decoder is not None:
        return _decode(decoder, response)

    if is_none_type(endpoint.return_type):
        return None

    if is_response_type(endpoint.return_type):
        return response

    raise RuntimeError("Internal error: decoder was None for a decodable return type.")


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


async def _aresult(endpoint: Endpoint, decoder: Decoder | None, response: httpx2.Response) -> object:
    """The ``async`` counterpart of ``_result``: an ``AsyncStreamDecoder``'s output is an async iterator."""
    if isinstance(decoder, AsyncStreamDecoder):
        return await _astream(cast(AsyncStreamDecoder[object], decoder), response)
    return _result(endpoint, decoder, response)


async def _astream(decoder: AsyncStreamDecoder[object], response: httpx2.Response) -> AsyncIterator[object]:
    """Run an ``AsyncStreamDecoder`` on a streamed ``response``, making sure the response gets closed.

    The ``async`` counterpart of ``_decode`` for stream decoders: close the response if the
    decoder raises, and wrap its iterator so the response closes when iteration ends.
    """
    try:
        items = decoder(response)
    except BaseException:
        await response.aclose()
        raise
    return _aclose_when_done(items, response)


async def _aclose_when_done[T](items: AsyncIterable[T], response: httpx2.Response) -> AsyncIterator[T]:
    """Yield from ``items``, then close them and ``response`` however iteration ends.

    The exit stack closes them on exhaustion, on an exception, and when the iterator is closed
    with ``aclose()``. If the caller stops iterating without closing it, the event loop closes
    it when it's garbage-collected (the async generator finalizer hook).
    """
    async with AsyncExitStack() as stack:
        stack.push_async_callback(response.aclose)
        # What `yield from` does for the sync version: close the decoder's own generator too.
        # Callbacks run last in, first out: the generator, then the response.
        if isinstance(items, AsyncGenerator):
            stack.push_async_callback(items.aclose)
        async for item in items:
            yield item


@dataclass(frozen=True)
class ApiMethod:
    method: MethodType

    @overload
    def __call__[D](
        self,
        path: str = "",
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
        path: str = "",
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
        path: str = "",
        *,
        decoder: Decoder | None = None,
        deprecated: DeprecatedType | None = None,
        tags: list[str] | None = None,
        timeout: httpx2.Timeout | float | None = None,
        raise_for_status: bool | None = None,
        validate_arguments: bool | None = None,
    ) -> DecodedEndpointDecorator[Any] | RawEndpointDecorator:
        """Build a decorator that registers an endpoint for this HTTP method.

        It decorates a ``def`` method, for a ``ClientX``, or an ``async def`` method, for
        an ``AsyncClientX``; calling an ``async def`` endpoint returns an awaitable.

        Args:
            path: URL path template for the endpoint (e.g., ``/v1/users/{user_id}``).
                Defaults to ``""``: the client's base URL, or on a ``Resource``, its
                prefix itself, so ``@get()`` on a resource with ``prefix="/users"``
                is ``GET /users``.
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
                call, spec = _prepare(
                    endpoint, request_factory, endpoint_name, owner=_self, client=client, args=args, kwargs=kwargs
                )

                started = time.perf_counter()
                try:
                    response = send_request(
                        client, method=endpoint.method, path=spec.path, stream=endpoint.stream, **spec.parts
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
                # `_result` is typed `object`, since it serves every decoder. The decorator's overloads already
                # check that the decoder's output matches the method's return type, `R`, so the cast restates that.
                return cast(R, _result(endpoint, decoder, response))

            @wraps(func)
            # It returns the awaited value, so its return type isn't `R`: for an `async def` method, `R` is the
            # coroutine type, which calling `async_wrapper` produces. So instead of casting the result as the
            # sync wrapper does, the wrapper itself is cast to the method's type below.
            async def async_wrapper(_self: T, /, *args: P.args, **kwargs: P.kwargs) -> object:
                client = async_client_of(_self)
                call, spec = _prepare(
                    endpoint, request_factory, endpoint_name, owner=_self, client=client, args=args, kwargs=kwargs
                )

                started = time.perf_counter()
                try:
                    response = await asend_request(
                        client, method=endpoint.method, path=spec.path, stream=endpoint.stream, **spec.parts
                    )
                except Exception as error:
                    log_endpoint_call(call, started=started, error=error)
                    raise

                if response.is_error and _raises_for_status(endpoint, client):
                    try:
                        await _araise_status_error(response)
                    except Exception as error:
                        log_endpoint_call(call, started=started, status=response.status_code, error=error)
                        raise
                log_endpoint_call(call, started=started, status=response.status_code)
                return await _aresult(endpoint, decoder, response)

            # Either way, the endpoint function has the decorated method's type, `Callable[Concatenate[T, P], R]`.
            endpoint_function = (
                cast(Callable[Concatenate[T, P], R], async_wrapper) if inspect.iscoroutinefunction(func) else wrapper
            )
            endpoint.func = endpoint_function
            register_endpoint_function(endpoint_function, endpoint)
            return endpoint_function

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
