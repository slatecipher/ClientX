import warnings
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import wraps
from typing import Any, Concatenate, Protocol, cast, overload

from httpx2 import USE_CLIENT_DEFAULT, Response, Timeout

from clientx._client import AsyncClientX, AsyncResource, ClientX, EndpointOwner, Resource, client_of
from clientx._decoding import adecode, araise_status_error, decode, raise_status_error
from clientx._endpoint import Endpoint
from clientx._registry import register_endpoint_function
from clientx._signature import BoundCall, inspect_definition
from clientx._types import Decoder, MethodType, ToolOptions, UseClientDefault


# --- What type checkers see ---------------------------------------------------
class EndpointDecorator(Protocol):
    """The decorator a verb returns without ``decoder=``.

    The endpoint keeps its signature. Each overload is limited to its kind of
    class: a ``def`` endpoint on a ``ClientX`` or ``Resource``, an ``async def``
    one on an ``AsyncClientX`` or ``AsyncResource``. So a ``def`` endpoint on an
    async class is reported. An ``async def`` endpoint on a sync class isn't: to
    a type checker it's a ``def`` that returns a coroutine, so only the check
    when the class is defined catches it. The ``def`` overload is repeated last,
    as in ``DecodedEndpointDecorator``.
    """

    @overload
    def __call__[Owner: ClientX | Resource, **P, R](
        self, func: Callable[Concatenate[Owner, P], R], /
    ) -> Callable[Concatenate[Owner, P], R]: ...
    @overload
    def __call__[Owner: AsyncClientX | AsyncResource, **P, R](
        self, func: Callable[Concatenate[Owner, P], Coroutine[Any, Any, R]], /
    ) -> Callable[Concatenate[Owner, P], Coroutine[Any, Any, R]]: ...
    @overload
    def __call__[Owner: ClientX | Resource, **P, R](
        self, func: Callable[Concatenate[Owner, P], R], /
    ) -> Callable[Concatenate[Owner, P], R]: ...


class DecodedEndpointDecorator[D](Protocol):
    """The decorator a verb returns with ``decoder=``.

    A ``def`` endpoint must return ``D``, the decoder's return type, and an
    ``async def`` endpoint's coroutine must return it, so type checkers report
    an endpoint whose annotation doesn't match its decoder. Each overload is
    limited to its kind of class: if both could match, as when ``D`` is ``Any``,
    mypy would see the endpoint as untyped.

    The ``def`` overload comes first and again last: when none matches, mypy
    reports the first overload's error and pyright the last's, so both name the
    ``def`` form, the common case.
    """

    @overload
    def __call__[Owner: ClientX | Resource, **P](
        self, func: Callable[Concatenate[Owner, P], D], /
    ) -> Callable[Concatenate[Owner, P], D]: ...
    @overload
    def __call__[Owner: AsyncClientX | AsyncResource, **P](
        self, func: Callable[Concatenate[Owner, P], Coroutine[Any, Any, D]], /
    ) -> Callable[Concatenate[Owner, P], Coroutine[Any, Any, D]]: ...
    @overload
    def __call__[Owner: ClientX | Resource, **P](
        self, func: Callable[Concatenate[Owner, P], D], /
    ) -> Callable[Concatenate[Owner, P], D]: ...


# --- The verb decorators ------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Method:
    """An HTTP verb's endpoint decorator, such as ``method.get``."""

    method: MethodType

    @overload
    def __call__(
        self,
        path: str = "",
        *,
        decoder: None = None,
        stream: bool = False,
        deprecated: str | None = None,
        tags: list[str] | None = None,
        tool_options: ToolOptions | None = None,
        timeout: Timeout | float | None | UseClientDefault = USE_CLIENT_DEFAULT,
        raise_for_status: bool | None = None,
    ) -> EndpointDecorator: ...
    @overload
    def __call__[D](
        self,
        path: str = "",
        *,
        decoder: Callable[[Response], D],
        stream: bool = False,
        deprecated: str | None = None,
        tags: list[str] | None = None,
        tool_options: ToolOptions | None = None,
        timeout: Timeout | float | None | UseClientDefault = USE_CLIENT_DEFAULT,
        raise_for_status: bool | None = None,
    ) -> DecodedEndpointDecorator[D]: ...
    def __call__(
        self,
        path: str = "",
        *,
        decoder: Decoder | None = None,
        stream: bool = False,
        deprecated: str | None = None,
        tags: list[str] | None = None,
        tool_options: ToolOptions | None = None,
        timeout: Timeout | float | None | UseClientDefault = USE_CLIENT_DEFAULT,
        raise_for_status: bool | None = None,
    ) -> Any:
        """Return the decorator that turns a method into an endpoint.

        Without ``decoder=``, the endpoint keeps its own signature. With one, it
        must return what the decoder returns: type checkers report a mismatch at
        the decorator.

        Args:
            path: The path template, such as ``"/users/{user_id}"``, relative to
                the client's base URL. A resource joins its prefix onto it.
            decoder: Turns the ``httpx2.Response`` into the return value, in
                place of the decoding the return annotation implies. A generator
                decoder streams, for an endpoint annotated ``-> Iterator[...]``
                (an async generator for ``-> AsyncIterator[...]``).
            stream: Return the open, unread response, which the caller reads and
                closes. Only with ``-> Response`` and no ``decoder=``.
            deprecated: The message of a ``DeprecationWarning`` each call emits.
            tags: Labels that group endpoints, each kept once. A resource's tags
                go in front. ClientX doesn't use them itself yet.
            tool_options: Hints about what the endpoint does, for its tool. Each
                one set is used as it is, and each left out comes from the HTTP
                method; see ``ToolOptions``.
            timeout: The request timeout, as httpx2 takes it: the default uses
                the client's, and ``None`` turns it off.
            raise_for_status: Whether a 4xx or 5xx response raises
                ``httpx2.HTTPStatusError``; ``None`` uses the client's setting.
        """

        def decorator[T: EndpointOwner, **P, R](func: Callable[Concatenate[T, P], R]) -> Callable[Concatenate[T, P], R]:
            endpoint = Endpoint(
                method=self.method,
                raw_path=path,
                signature=inspect_definition(func, "Endpoint"),
                tags=list(tags or ()),
                timeout=timeout,
                raise_for_status=raise_for_status,
                decoder=decoder,
                stream_response=stream,
                deprecated=deprecated,
                tool_options=tool_options,
            )

            @wraps(func)
            def wrapper(_self: T, /, *args: P.args, **kwargs: P.kwargs) -> R:
                if endpoint.deprecated is not None:
                    # `stacklevel=2` names the caller's line. The warning must
                    # stay in the wrapper's own frame.
                    warnings.warn(endpoint.deprecated, DeprecationWarning, stacklevel=2)
                client = client_of(_self, ClientX)
                bound = endpoint.bind(_self, *args, **kwargs)
                _check_arguments(endpoint, client, bound)
                url, request_arguments = endpoint.request_arguments(bound)
                request = client.build_request(endpoint.method, url, **request_arguments)
                response = client.send(request, stream=endpoint.stream)
                if response.is_error and _raises_for_status(endpoint, client):
                    raise_status_error(response)
                if endpoint.stream_response:
                    return cast(R, response)  # Open and unread: the caller reads and closes it.
                return cast(R, decode(endpoint.decoder, response, stream=endpoint.stream))

            @wraps(func)
            async def async_wrapper(_self: T, /, *args: P.args, **kwargs: P.kwargs) -> object:
                if endpoint.deprecated is not None:
                    warnings.warn(endpoint.deprecated, DeprecationWarning, stacklevel=2)
                client = client_of(_self, AsyncClientX)
                bound = endpoint.bind(_self, *args, **kwargs)
                _check_arguments(endpoint, client, bound)
                url, request_arguments = endpoint.request_arguments(bound)
                request = client.build_request(endpoint.method, url, **request_arguments)
                response = await client.send(request, stream=endpoint.stream)
                if response.is_error and _raises_for_status(endpoint, client):
                    await araise_status_error(response)
                if endpoint.stream_response:
                    return response  # Open and unread: the caller reads and closes it.
                return await adecode(endpoint.decoder, response, stream=endpoint.stream)

            endpoint_function = (
                cast(Callable[Concatenate[T, P], R], async_wrapper) if endpoint.signature.is_async else wrapper
            )
            register_endpoint_function(endpoint_function, endpoint)
            return endpoint_function

        return decorator


def _check_arguments(endpoint: Endpoint, client: ClientX | AsyncClientX, bound: BoundCall) -> None:
    """Check a call's arguments if the client has ``validate_arguments=True``.

    Raises:
        ArgumentError: If an argument the caller passed doesn't fit.
    """
    if client.__clientx_validate_arguments__:
        endpoint.check_arguments(bound)


def _raises_for_status(endpoint: Endpoint, client: ClientX | AsyncClientX) -> bool:
    """Return whether ``endpoint`` raises for a 4xx or 5xx response.

    Its own setting, if it has one, wins over the client's. Not ``or``: an
    endpoint's ``False`` must win over the client's ``True``.
    """
    return client.__clientx_raise_for_status__ if endpoint.raise_for_status is None else endpoint.raise_for_status
