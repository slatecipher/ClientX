"""Decode an endpoint's response as its return annotation says.

The return annotation decides how a response becomes the value an endpoint returns,
so most endpoints need no ``decoder=``:

    -> None             nothing
    -> Response         the response, read (unread with ``stream=True``)
    -> str / -> bytes   the body as text / as bytes
    -> Iterator[str]    the body streamed as lines
    -> Iterator[bytes]  the body streamed as chunks
    -> anything else    the JSON body, validated by a ``TypeAdapter``

An ``async def`` endpoint streams with ``AsyncIterator[str]`` and
``AsyncIterator[bytes]`` instead.

An endpoint's own ``decoder=``, any callable that takes an ``httpx2.Response``, replaces
the decoder the annotation implies. An ``Iterator`` or ``AsyncIterator`` annotation streams
the response either way, and ``decode`` / ``adecode`` close it when iteration ends.

A 4xx or 5xx response isn't decoded when the endpoint checks the status: the wrapper calls
``raise_status_error`` (``araise_status_error`` for ``async def``) instead, which raises
``httpx2.HTTPStatusError``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Iterable, Iterator
from contextlib import AsyncExitStack
from types import NoneType
from typing import TYPE_CHECKING, Any, cast, get_args, get_origin

from httpx2 import Response
from pydantic import PydanticSchemaGenerationError, TypeAdapter

from clientx.exceptions import DefinitionError

if TYPE_CHECKING:
    from clientx._signature import ReturnInfo
    from clientx._types import Decoder


def is_stream(returns: ReturnInfo, *, is_async: bool) -> bool:
    """Return whether an endpoint's return annotation makes it stream its response.

    A ``def`` endpoint streams with ``-> Iterator[T]``, an ``async def`` one with
    ``-> AsyncIterator[T]``.

    Raises:
        DefinitionError: If the annotation is the other kind of endpoint's iterator.
    """
    origin = get_origin(returns.base_type)
    if is_async and origin is Iterator:
        raise DefinitionError("An `async def` endpoint streams an AsyncIterator: annotate it -> AsyncIterator[...].")
    if not is_async and origin is AsyncIterator:
        raise DefinitionError("A plain `def` endpoint streams an Iterator: annotate it -> Iterator[...].")
    return origin is (AsyncIterator if is_async else Iterator)


def default_decoder(returns: ReturnInfo, *, is_async: bool) -> Decoder | None:
    """Return the decoder an endpoint's return annotation implies, or ``None`` for ``-> None``.

    It's for an endpoint without ``decoder=``, and dispatches on ``returns.base_type``, so
    ``Annotated`` and ``type`` aliases don't hide the type. The ``TypeAdapter`` gets the full
    ``returns.annotation``, so ``Annotated`` constraints are validated too. It's built here,
    once, so a type Pydantic can't validate fails now rather than on the first call.

    Raises:
        DefinitionError: If the annotation needs a ``decoder=``: it streams items other than ``str``
            or ``bytes``, or names a type Pydantic can't validate. Also if it's the other kind
            of endpoint's iterator.
    """
    return_type = returns.base_type
    if return_type is None or return_type is NoneType:
        return None
    if return_type is Response:
        return _response
    if return_type is str:
        return _text
    if return_type is bytes:
        return _content
    if is_stream(returns, is_async=is_async):
        item = get_args(return_type)[0]
        if item is str:
            return _alines if is_async else _lines
        if item is bytes:
            return _achunks if is_async else _chunks
        raise DefinitionError(
            f"Streaming {_type_name(item)} items needs a decoder=: ClientX streams str (lines) and bytes "
            "(chunks) by itself."
        )
    try:
        adapter = TypeAdapter[Any](returns.annotation)
    except PydanticSchemaGenerationError as error:
        raise DefinitionError(
            f"Pydantic can't validate {_type_name(returns.annotation)}: annotate a type it supports, "
            "or pass a decoder=."
        ) from error
    return lambda response: adapter.validate_json(response.content)


def _type_name(annotation: Any) -> str:
    return annotation.__qualname__ if isinstance(annotation, type) else repr(annotation)


def _response(response: Response) -> Response:
    return response


def _text(response: Response) -> str:
    return response.text


def _content(response: Response) -> bytes:
    return response.content


def _lines(response: Response) -> Iterator[str]:
    return response.iter_lines()


def _chunks(response: Response) -> Iterator[bytes]:
    return response.iter_bytes()


def _alines(response: Response) -> AsyncIterator[str]:
    return response.aiter_lines()


def _achunks(response: Response) -> AsyncIterator[bytes]:
    return response.aiter_bytes()


def raise_status_error(response: Response) -> None:
    """Raise ``httpx2.HTTPStatusError`` for ``response``, which must be a 4xx or 5xx.

    The caller checks ``response.is_error`` first: called on a 3xx this would raise, and on
    a successful streamed response it would read the body the decoder should stream. The
    body is read, so the error keeps it, and the response is closed, so a streamed one frees
    its connection. For a response that isn't streamed, httpx2 has already done both, and
    they do nothing.
    """
    try:
        response.read()
    finally:
        response.close()
    response.raise_for_status()


async def araise_status_error(response: Response) -> None:
    """Raise ``httpx2.HTTPStatusError`` for a 4xx or 5xx response from an ``httpx2.AsyncClient``.

    See ``raise_status_error``.
    """
    try:
        await response.aread()
    finally:
        await response.aclose()
    response.raise_for_status()


def decode(decoder: Decoder | None, response: Response, *, stream: bool) -> object:
    """Return what a ``def`` endpoint returns: ``decoder``'s output, or ``None`` without a decoder.

    For a streamed response, ``decoder`` returns an iterator. The response is closed if the
    decoder raises, and otherwise when iteration finishes, stops early, or fails.

    Args:
        decoder: The endpoint's decoder, or ``None`` for an endpoint that returns nothing.
        response: The response, read already unless ``stream`` is true.
        stream: Whether the response was sent in streaming mode.
    """
    if decoder is None:
        return None
    if not stream:
        return decoder(response)
    try:
        items = cast("Iterable[object]", decoder(response))
    except BaseException:
        response.close()
        raise
    return _close_when_done(items, response)


def _close_when_done(items: Iterable[object], response: Response) -> Iterator[object]:
    """Yield from ``items``, then close ``response`` however iteration ends.

    The ``finally`` block runs on exhaustion, on an exception, and when the generator is
    closed (explicitly, or by a ``for`` loop that breaks early). An iterator that's never
    started, or is kept alive, stays open until it's closed or garbage-collected.
    """
    try:
        yield from items
    finally:
        response.close()


async def adecode(decoder: Decoder | None, response: Response, *, stream: bool) -> object:
    """Return what an ``async def`` endpoint returns, as ``decode`` does; a stream is an async iterator."""
    if decoder is None:
        return None
    if not stream:
        return decoder(response)
    try:
        items = cast("AsyncIterable[object]", decoder(response))
    except BaseException:
        await response.aclose()
        raise
    return _aclose_when_done(items, response)


async def _aclose_when_done(items: AsyncIterable[object], response: Response) -> AsyncIterator[object]:
    """Yield from ``items``, then close them and ``response`` however iteration ends.

    The exit stack closes them on exhaustion, on an exception, and when the iterator is
    closed with ``aclose()``. If the caller stops iterating without closing it, the event
    loop closes it when it's garbage-collected (the async generator finalizer hook).
    """
    async with AsyncExitStack() as stack:
        stack.push_async_callback(response.aclose)
        # What `yield from` does for the sync version: close the decoder's own generator too.
        # Callbacks run last in, first out: the generator, then the response.
        if isinstance(items, AsyncGenerator):
            stack.push_async_callback(items.aclose)
        async for item in items:
            yield item
