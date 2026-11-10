"""4xx and 5xx responses raise ``httpx2.HTTPStatusError`` unless the client or the endpoint turns it off."""

from collections.abc import Callable, Iterator
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel

from clientx import ClientX, Resource, Response
from clientx.decoders import ModelDecoder, StreamLinesDecoder, StreamResponseDecoder
from clientx.methods import delete, get
from clientx.tools import list_tools


class User(BaseModel):
    id: int


class TrackedStream(httpx2.SyncByteStream):
    """A response body that isn't read until something iterates it, and records when it's closed."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self.chunks

    def close(self) -> None:
        self.closed = True


def respond(status: int, **kwargs: Any) -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda request: httpx2.Response(status, **kwargs))


ERROR_BODY = {"error": "no such user"}


class Users(Resource, prefix="/users"):
    @get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: int) -> User: ...


class API(ClientX):
    users = Users()

    @get("/users/{user_id}", decoder=ModelDecoder(User))
    def decoded(self, user_id: int) -> User: ...

    @get("/raw")
    def raw(self) -> Response: ...

    @delete("/users/{user_id}")
    def remove(self, user_id: int) -> None: ...

    @get("/raw-unchecked", raise_for_status=False)
    def raw_unchecked(self) -> Response: ...

    @get("/raw-checked", raise_for_status=True)
    def raw_checked(self) -> Response: ...

    @get("/lines", decoder=StreamLinesDecoder())
    def lines(self) -> Iterator[str]: ...

    @get("/open", decoder=StreamResponseDecoder())
    def open_response(self) -> Response: ...


CALLS: dict[str, Callable[[API], object]] = {
    "decoder": lambda api: api.decoded(1),
    "-> Response": lambda api: api.raw(),
    "-> None": lambda api: api.remove(1),
    "resource": lambda api: api.users.retrieve(1),
}


@pytest.mark.parametrize("status", [400, 404, 500, 503])
@pytest.mark.parametrize("call", CALLS.values(), ids=CALLS.keys())
def test_error_statuses_raise_by_default_with_the_body_readable(status: int, call: Callable[[API], object]):
    api = API("https://api.example.com", transport=respond(status, json=ERROR_BODY))

    with pytest.raises(httpx2.HTTPStatusError) as raised:
        call(api)

    assert raised.value.response.status_code == status
    assert raised.value.response.json() == ERROR_BODY


def test_the_decoder_doesnt_run_on_an_error_status():
    seen: list[int] = []

    def record(response: httpx2.Response) -> int:
        seen.append(response.status_code)
        return response.status_code

    class Counter(ClientX):
        @get("/count", decoder=record)
        def count(self) -> int: ...

    with pytest.raises(httpx2.HTTPStatusError):
        Counter("https://api.example.com", transport=respond(404)).count()

    assert seen == []


@pytest.mark.parametrize("status", [200, 201, 204, 301, 302, 304])
def test_success_and_unfollowed_redirect_statuses_are_returned(status: int):
    headers = {"Location": "https://api.example.com/elsewhere"} if status in {301, 302} else {}
    api = API("https://api.example.com", transport=respond(status, headers=headers))

    assert api.raw().status_code == status


def test_the_client_can_turn_it_off():
    api = API("https://api.example.com", raise_for_status=False, transport=respond(404, json=ERROR_BODY))

    assert api.raw().status_code == 404
    assert api.remove(1) is None


def test_the_endpoint_setting_wins_over_the_clients():
    checked_client = API("https://api.example.com", transport=respond(404))
    unchecked_client = API("https://api.example.com", raise_for_status=False, transport=respond(404))

    assert checked_client.raw_unchecked().status_code == 404
    with pytest.raises(httpx2.HTTPStatusError):
        unchecked_client.raw_checked()


def test_a_resource_follows_its_clients_setting():
    api = API("https://api.example.com", raise_for_status=False, transport=respond(404, json={"id": 404}))

    assert api.users.retrieve(1) == User(id=404)


@pytest.mark.parametrize("call", [API.lines, API.open_response], ids=["StreamLinesDecoder", "StreamResponseDecoder"])
def test_a_streamed_error_is_read_then_closed(call: Callable[[API], object]):
    body = TrackedStream([b'{"error": ', b'"no such user"}'])
    api = API("https://api.example.com", transport=respond(404, stream=body))

    with pytest.raises(httpx2.HTTPStatusError) as raised:
        call(api)

    assert raised.value.response.json() == ERROR_BODY
    assert body.closed


def test_a_streamed_success_isnt_read_before_the_decoder():
    body = TrackedStream([b"one\n", b"two\n"])
    api = API("https://api.example.com", transport=respond(200, stream=body))

    lines = api.lines()

    assert not body.closed
    assert list(lines) == ["one", "two"]
    assert body.closed


def test_a_tool_call_raises_the_status_error():
    api = API("https://api.example.com", transport=respond(404, json=ERROR_BODY))
    tool = next(tool for tool in list_tools(api) if tool.name == "decoded")

    with pytest.raises(httpx2.HTTPStatusError):
        tool.call({"user_id": 1})
