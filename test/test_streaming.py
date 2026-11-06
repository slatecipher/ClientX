"""Streamed responses must always release their connection.

These tests go through the real ``ClientX.send`` with a mock transport whose
byte stream records when it is closed, which is what returns the connection
to the pool.
"""

from collections.abc import Iterator

import httpx2
import pytest
from pydantic import BaseModel

from clientx import ClientX, Response
from clientx.decoders import ModelDecoder, StreamDecoder, StreamLinesDecoder
from clientx.methods import get


class TrackedStream(httpx2.SyncByteStream):
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self.body.splitlines(keepends=True)

    def close(self) -> None:
        self.closed = True


class User(BaseModel):
    name: str


class HeaderDecoder(StreamDecoder[str]):
    """A stream decoder that never touches the body, so httpx2 never closes it."""

    def __call__(self, response: httpx2.Response) -> Iterator[str]:
        yield response.headers["x-id"]


class FailingDecoder(StreamDecoder[str]):
    """A stream decoder that fails before returning an iterator."""

    def __call__(self, response: httpx2.Response) -> Iterator[str]:
        raise ValueError("decoder failed")


class StreamingAPI(ClientX):
    @get("/fire", stream=True)
    def fire(self) -> None: ...

    @get("/events", decoder=StreamLinesDecoder())
    def events(self) -> Iterator[str]: ...

    @get("/header", decoder=HeaderDecoder())
    def header(self) -> Iterator[str]: ...

    @get("/user", decoder=ModelDecoder(User), stream=True)
    def user(self) -> User: ...

    @get("/raw", stream=True)
    def raw(self) -> Response: ...

    @get("/fail", decoder=FailingDecoder())
    def fail(self) -> Iterator[str]: ...


@pytest.fixture
def streams() -> list[TrackedStream]:
    return []


@pytest.fixture
def api(streams: list[TrackedStream]) -> StreamingAPI:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = b'{"name": "Ada"}' if request.url.path == "/user" else b"a\nb\nc\n"
        stream = TrackedStream(body)
        streams.append(stream)
        return httpx2.Response(200, headers={"x-id": "42"}, stream=stream)

    return StreamingAPI("https://example.test", transport=httpx2.MockTransport(handler))


def test_none_return_closes_streamed_response(api: StreamingAPI, streams: list[TrackedStream]):
    assert api.fire() is None
    assert streams[0].closed


def test_stream_decoder_closes_after_full_iteration(api: StreamingAPI, streams: list[TrackedStream]):
    assert list(api.events()) == ["a", "b", "c"]
    assert streams[0].closed


def test_stream_decoder_closes_after_early_break(api: StreamingAPI, streams: list[TrackedStream]):
    for line in api.events():
        assert line == "a"
        break

    assert streams[0].closed


def test_closing_a_partially_consumed_stream_closes_the_response(api: StreamingAPI, streams: list[TrackedStream]):
    lines = api.events()
    assert next(lines) == "a"
    assert not streams[0].closed

    lines.close()  # type: ignore[attr-defined]  # the returned iterator is a generator

    assert streams[0].closed


def test_stream_decoder_that_ignores_the_body_still_closes(api: StreamingAPI, streams: list[TrackedStream]):
    assert list(api.header()) == ["42"]
    assert streams[0].closed


def test_buffered_decoder_on_streamed_endpoint_reads_and_closes(api: StreamingAPI, streams: list[TrackedStream]):
    assert api.user() == User(name="Ada")
    assert streams[0].closed


def test_decoder_error_closes_streamed_response(api: StreamingAPI, streams: list[TrackedStream]):
    with pytest.raises(ValueError, match="decoder failed"):
        api.fail()

    assert streams[0].closed


def test_response_return_leaves_streamed_response_open_for_the_caller(api: StreamingAPI, streams: list[TrackedStream]):
    response = api.raw()
    assert not streams[0].closed

    assert list(response.iter_lines()) == ["a", "b", "c"]
    assert streams[0].closed
