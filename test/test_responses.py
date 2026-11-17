"""Responses: decoded as the return annotation says, streamed and closed, and raised for 4xx and 5xx."""

import functools
import re
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Annotated, Any

import httpx2
import pytest
from pydantic import BaseModel, Field, ValidationError

from clientx import AsyncClientX, ClientX, DefinitionError, Response, method

type MockTransport = Callable[..., httpx2.MockTransport]

BASE_URL = "https://api.example.com"


class User(BaseModel):
    id: int
    name: str


type UserId = Annotated[int, Field(gt=0)]


class TrackedStream(httpx2.SyncByteStream):
    """A response body sent in chunks, which records whether it was closed."""

    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self.chunks

    def close(self) -> None:
        self.closed = True


class TrackedAsyncStream(httpx2.AsyncByteStream):
    """The async counterpart of ``TrackedStream``."""

    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def streaming(stream: httpx2.SyncByteStream | httpx2.AsyncByteStream, status: int = 200) -> httpx2.MockTransport:
    """Return a transport that answers with ``stream`` as the body, so it's read only as it's iterated."""
    return httpx2.MockTransport(lambda request: httpx2.Response(status, stream=stream))


# Decoding by return annotation


def test_none_returns_nothing(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.delete("/users/{user_id}")
        def remove(self, user_id: int) -> None: ...

    assert API(BASE_URL, transport=mock_transport(json={"ignored": True})).remove(1) is None


def test_response_returns_the_response_already_read(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/health")
        def health(self) -> Response: ...

    response = API(BASE_URL, transport=mock_transport(status=204)).health()
    assert isinstance(response, httpx2.Response)
    assert (response.status_code, response.is_closed, response.content) == (204, True, b"")


def test_str_and_bytes_return_the_body(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/text")
        def text(self) -> str: ...

        @method.get("/raw")
        def raw(self) -> bytes: ...

    api = API(BASE_URL, transport=mock_transport(content="héllo".encode()))
    assert (api.text(), api.raw()) == ("héllo", "héllo".encode())


def test_any_other_type_is_validated_from_json(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/users/{user_id}")
        def user(self, user_id: int) -> User: ...

        @method.get("/users")
        def users(self) -> list[User]: ...

    assert API(BASE_URL, transport=mock_transport(json={"id": 1, "name": "Ada"})).user(1) == User(id=1, name="Ada")
    assert API(BASE_URL, transport=mock_transport(json=[{"id": 2, "name": "Bo"}])).users() == [User(id=2, name="Bo")]


def test_annotated_constraints_are_validated_too(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/next-id")
        def next_id(self) -> UserId: ...

    assert API(BASE_URL, transport=mock_transport(json=5)).next_id() == 5
    with pytest.raises(ValidationError, match="greater than 0"):
        API(BASE_URL, transport=mock_transport(json=0)).next_id()


def test_a_decoder_replaces_the_one_the_annotation_implies(mock_transport: MockTransport) -> None:
    def status_of(response: httpx2.Response) -> int:
        return response.status_code

    class API(ClientX):
        @method.post("/jobs", decoder=status_of)
        def submit(self) -> int: ...

    assert API(BASE_URL, transport=mock_transport(status=202)).submit() == 202


@pytest.mark.anyio
async def test_async_endpoints_decode_too(mock_transport: MockTransport) -> None:
    class API(AsyncClientX):
        @method.get("/users/{user_id}")
        async def user(self, user_id: int) -> User: ...

    api = API(BASE_URL, transport=mock_transport(json={"id": 1, "name": "Ada"}))
    assert await api.user(1) == User(id=1, name="Ada")


# Streaming


def test_an_iterator_of_str_streams_lines_and_closes_the_response() -> None:
    class API(ClientX):
        @method.get("/logs")
        def logs(self) -> Iterator[str]: ...

    stream = TrackedStream(b"first\nsec", b"ond\n")
    lines = API(BASE_URL, transport=streaming(stream)).logs()
    assert not stream.closed
    assert list(lines) == ["first", "second"]
    assert stream.closed


def test_an_iterator_of_bytes_streams_chunks() -> None:
    class API(ClientX):
        @method.get("/download")
        def download(self) -> Iterator[bytes]: ...

    stream = TrackedStream(b"ab", b"cd")
    assert b"".join(API(BASE_URL, transport=streaming(stream)).download()) == b"abcd"
    assert stream.closed


def test_a_stream_left_early_is_closed() -> None:
    class API(ClientX):
        @method.get("/logs")
        def logs(self) -> Iterator[str]: ...

    stream = TrackedStream(b"first\n", b"second\n")
    for _line in API(BASE_URL, transport=streaming(stream)).logs():
        break
    # The loop held the only reference, so the generator is closed when the loop ends.
    assert stream.closed


def test_a_stream_is_closed_if_its_decoder_fails() -> None:
    def broken(response: httpx2.Response) -> Iterator[str]:
        raise RuntimeError("decoder failed")

    class API(ClientX):
        @method.get("/logs", decoder=broken)
        def logs(self) -> Iterator[str]: ...

    stream = TrackedStream(b"line\n")
    with pytest.raises(RuntimeError, match="decoder failed"):
        API(BASE_URL, transport=streaming(stream)).logs()
    assert stream.closed


@pytest.mark.anyio
async def test_an_async_iterator_streams_and_closes_the_response() -> None:
    class API(AsyncClientX):
        @method.get("/logs")
        async def logs(self) -> AsyncIterator[str]: ...

        @method.get("/download")
        async def download(self) -> AsyncIterator[bytes]: ...

    lines_stream = TrackedAsyncStream(b"first\nsec", b"ond\n")
    lines = await API(BASE_URL, transport=streaming(lines_stream)).logs()
    assert [line async for line in lines] == ["first", "second"]
    assert lines_stream.closed

    chunks_stream = TrackedAsyncStream(b"ab", b"cd")
    chunks = await API(BASE_URL, transport=streaming(chunks_stream)).download()
    assert [chunk async for chunk in chunks] == [b"ab", b"cd"]
    assert chunks_stream.closed


@pytest.mark.anyio
async def test_an_async_stream_closed_early_closes_the_response() -> None:
    class API(AsyncClientX):
        @method.get("/logs")
        async def logs(self) -> AsyncIterator[str]: ...

    stream = TrackedAsyncStream(b"first\n", b"second\n")
    lines = await API(BASE_URL, transport=streaming(stream)).logs()
    assert await anext(lines) == "first"
    await lines.aclose()  # pyright: ignore[reportAttributeAccessIssue]  # an async generator underneath
    assert stream.closed


# 4xx and 5xx


def test_an_error_status_raises_with_the_body_kept(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/users/{user_id}")
        def user(self, user_id: int) -> User: ...

    with pytest.raises(httpx2.HTTPStatusError) as caught:
        API(BASE_URL, transport=mock_transport(status=404, json={"detail": "no such user"})).user(1)
    assert caught.value.response.json() == {"detail": "no such user"}


def test_a_streamed_error_is_read_and_closed_before_raising() -> None:
    class API(ClientX):
        @method.get("/logs")
        def logs(self) -> Iterator[str]: ...

    stream = TrackedStream(b"server ", b"error")
    with pytest.raises(httpx2.HTTPStatusError) as caught:
        API(BASE_URL, transport=streaming(stream, status=500)).logs()
    assert caught.value.response.text == "server error"
    assert stream.closed


def test_a_redirect_status_isnt_an_error(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/moved")
        def moved(self) -> Response: ...

    response = API(BASE_URL, transport=mock_transport(status=304)).moved()
    assert response.status_code == 304


@pytest.mark.parametrize(
    ("client_setting", "endpoint_setting", "raises"),
    [
        pytest.param(None, None, True, id="default: raise"),
        pytest.param(False, None, False, id="client off"),
        pytest.param(None, False, False, id="endpoint off"),
        pytest.param(False, True, True, id="endpoint on wins over client off"),
        pytest.param(True, False, False, id="endpoint off wins over client on"),
    ],
)
def test_raise_for_status_can_be_turned_off(
    client_setting: bool | None, endpoint_setting: bool | None, raises: bool, mock_transport: MockTransport
) -> None:
    class API(ClientX):
        @method.get("/users", raise_for_status=endpoint_setting)
        def users(self) -> Response: ...

    api = API(BASE_URL, transport=mock_transport(status=500), raise_for_status=client_setting)
    if raises:
        with pytest.raises(httpx2.HTTPStatusError):
            api.users()
    else:
        assert api.users().status_code == 500


@pytest.mark.anyio
async def test_async_endpoints_raise_for_status_too(mock_transport: MockTransport) -> None:
    class API(AsyncClientX):
        @method.get("/users")
        async def users(self) -> list[User]: ...

        @method.get("/logs")
        async def logs(self) -> AsyncIterator[str]: ...

    with pytest.raises(httpx2.HTTPStatusError):
        await API(BASE_URL, transport=mock_transport(status=503)).users()
    stream = TrackedAsyncStream(b"down")
    with pytest.raises(httpx2.HTTPStatusError) as caught:
        await API(BASE_URL, transport=streaming(stream, status=503)).logs()
    assert (caught.value.response.text, stream.closed) == ("down", True)


# Return annotations that can't be decoded


class Opaque:
    """A class Pydantic has no schema for."""


@pytest.mark.parametrize(
    ("returns", "message"),
    [
        pytest.param(Iterator[int], "Streaming int items needs a decoder=", id="stream of other items"),
        pytest.param(AsyncIterator[str], "A plain `def` endpoint streams an Iterator", id="async iterator on def"),
        pytest.param(Opaque, "Pydantic can't validate Opaque", id="type without a schema"),
    ],
)
def test_a_return_annotation_that_cant_be_decoded_fails_when_the_class_is_defined(returns: Any, message: str) -> None:
    with pytest.raises(DefinitionError, match=re.escape(message)):

        class API(ClientX):
            @method.get("/items")
            def items(self) -> returns: ...  # pyright: ignore[reportInvalidTypeForm]


def test_an_iterator_on_an_async_endpoint_fails() -> None:
    with pytest.raises(DefinitionError, match=re.escape("An `async def` endpoint streams an AsyncIterator")):

        class API(AsyncClientX):
            @method.get("/logs")
            async def logs(self) -> Iterator[str]: ...


def test_a_decoder_makes_any_return_annotation_work(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/opaque", decoder=lambda response: Opaque())
        def opaque(self) -> Opaque: ...

    assert isinstance(API(BASE_URL, transport=mock_transport()).opaque(), Opaque)


def test_an_endpoint_needs_a_return_annotation() -> None:
    with pytest.raises(DefinitionError, match=re.escape("needs a return annotation, such as `-> None`")):

        class API(ClientX):
            @method.get("/items")
            def items(self): ...


# An open streamed response: stream=True


def test_stream_true_returns_the_open_unread_response() -> None:
    class API(ClientX):
        @method.get("/files/{file_id}", stream=True)
        def download(self, file_id: str) -> Response: ...

    stream = TrackedStream(b"ab", b"cd")
    response = API(BASE_URL, transport=streaming(stream)).download("f1")
    assert not stream.closed
    assert list(response.iter_bytes()) == [b"ab", b"cd"]
    response.close()
    assert stream.closed


@pytest.mark.anyio
async def test_stream_true_returns_the_open_response_for_async_endpoints_too() -> None:
    class API(AsyncClientX):
        @method.get("/files/{file_id}", stream=True)
        async def download(self, file_id: str) -> Response: ...

    stream = TrackedAsyncStream(b"ab", b"cd")
    response = await API(BASE_URL, transport=streaming(stream)).download("f1")
    assert not stream.closed
    assert [chunk async for chunk in response.aiter_bytes()] == [b"ab", b"cd"]
    await response.aclose()
    assert stream.closed


def test_stream_true_still_raises_for_an_error_status() -> None:
    class API(ClientX):
        @method.get("/files/{file_id}", stream=True)
        def download(self, file_id: str) -> Response: ...

        @method.get("/raw/{file_id}", stream=True, raise_for_status=False)
        def raw(self, file_id: str) -> Response: ...

    error_stream = TrackedStream(b"gone")
    with pytest.raises(httpx2.HTTPStatusError) as caught:
        API(BASE_URL, transport=streaming(error_stream, status=410)).download("f1")
    assert (caught.value.response.text, error_stream.closed) == ("gone", True)

    open_stream = TrackedStream(b"gone")
    response = API(BASE_URL, transport=streaming(open_stream, status=410)).raw("f1")
    assert (response.status_code, open_stream.closed) == (410, False)
    response.close()


@pytest.mark.parametrize(
    ("returns", "decoder", "message"),
    [
        pytest.param(
            list[User], None, "has stream=True, which returns the open response, so annotate it -> Response", id="model"
        ),
        pytest.param(
            Iterator[bytes],
            None,
            "An Iterator annotation, such as -> Iterator[bytes], streams the body by itself",
            id="Iterator",
        ),
        pytest.param(Response, lambda response: response, "so it can't also take a decoder=", id="decoder="),
    ],
)
def test_stream_true_needs_a_response_annotation_and_no_decoder(
    returns: Any, decoder: Callable[[httpx2.Response], object] | None, message: str
) -> None:
    with pytest.raises(DefinitionError, match=re.escape(message)):

        class API(ClientX):
            @method.get("/files", stream=True, decoder=decoder)
            def files(self) -> returns: ...  # pyright: ignore[reportInvalidTypeForm]


# Custom decoders


class Event(BaseModel):
    id: int


def ndjson_events(response: httpx2.Response) -> Iterator[Event]:
    for line in response.iter_lines():
        yield Event.model_validate_json(line)


async def async_ndjson_events(response: httpx2.Response) -> AsyncIterator[Event]:
    async for line in response.aiter_lines():
        yield Event.model_validate_json(line)


async def coroutine_decoder(response: httpx2.Response) -> Event:
    return Event(id=1)


class AsyncDecoder:
    async def __call__(self, response: httpx2.Response) -> Event:
        return Event(id=1)


def test_a_generator_decoder_streams_typed_items() -> None:
    class API(ClientX):
        @method.get("/events", decoder=ndjson_events)
        def events(self) -> Iterator[Event]: ...

    stream = TrackedStream(b'{"id": 1}\n{"id"', b": 2}\n")
    assert list(API(BASE_URL, transport=streaming(stream)).events()) == [Event(id=1), Event(id=2)]
    assert stream.closed


@pytest.mark.anyio
async def test_an_async_generator_decoder_streams_typed_items() -> None:
    class API(AsyncClientX):
        @method.get("/events", decoder=async_ndjson_events)
        async def events(self) -> AsyncIterator[Event]: ...

    stream = TrackedAsyncStream(b'{"id": 1}\n{"id"', b": 2}\n")
    events = await API(BASE_URL, transport=streaming(stream)).events()
    assert [event async for event in events] == [Event(id=1), Event(id=2)]
    assert stream.closed


@pytest.mark.anyio
async def test_an_async_stream_is_closed_if_its_decoder_fails() -> None:
    def broken(response: httpx2.Response) -> AsyncIterator[Event]:
        raise RuntimeError("decoder failed")

    class API(AsyncClientX):
        @method.get("/events", decoder=broken)
        async def events(self) -> AsyncIterator[Event]: ...

    stream = TrackedAsyncStream(b'{"id": 1}\n')
    with pytest.raises(RuntimeError, match="decoder failed"):
        await API(BASE_URL, transport=streaming(stream)).events()
    assert stream.closed


def test_a_decoder_cant_go_with_none() -> None:
    with pytest.raises(DefinitionError, match=re.escape("is annotated -> None, so it returns nothing and can't take")):

        class API(ClientX):
            @method.get("/jobs", decoder=lambda response: "surprise")
            def submit(self) -> None: ...


@pytest.mark.parametrize(
    "decoder",
    [coroutine_decoder, functools.partial(coroutine_decoder), AsyncDecoder()],
    ids=["async def", "partial of an async def", "class with an async __call__"],
)
def test_an_async_def_decoder_fails(decoder: Callable[[httpx2.Response], object]) -> None:
    with pytest.raises(DefinitionError, match=re.escape("decoder= must be a plain function, not `async def`")):

        class API(AsyncClientX):
            @method.get("/event", decoder=decoder)
            async def event(self) -> Event: ...


def test_a_def_endpoint_cant_have_an_async_generator_decoder() -> None:
    with pytest.raises(
        DefinitionError, match=re.escape("is a plain `def`, so its decoder can't be an async generator")
    ):

        class API(ClientX):
            @method.get("/events", decoder=async_ndjson_events)
            def events(self) -> Iterator[Event]: ...


def test_an_async_def_endpoint_cant_have_a_plain_generator_decoder() -> None:
    with pytest.raises(DefinitionError, match=re.escape("so its stream decoder must be an async generator")):

        class API(AsyncClientX):
            @method.get("/events", decoder=ndjson_events)
            async def events(self) -> AsyncIterator[Event]: ...


def test_a_generator_decoder_needs_a_stream_annotation() -> None:
    with pytest.raises(DefinitionError, match=re.escape("so annotate the endpoint -> Iterator[...]")):

        class API(ClientX):
            @method.get("/events", decoder=ndjson_events)
            def events(self) -> list[Event]: ...

    with pytest.raises(DefinitionError, match=re.escape("so annotate the endpoint -> AsyncIterator[...]")):

        class AsyncAPI(AsyncClientX):
            @method.get("/events", decoder=async_ndjson_events)
            async def events(self) -> list[Event]: ...
