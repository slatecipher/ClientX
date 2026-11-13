"""AsyncClientX and AsyncResource: `async def` endpoints sent through an `httpx2.AsyncClient`."""

import gc
import inspect
import json
import logging
import re
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator
from typing import Annotated, Any, cast

import anyio
import httpx2
import pytest
from pydantic import BaseModel, Field

from clientx import AsyncClientX, AsyncResource, ClientX, DeprecatedMessage, Query, Resource, Response
from clientx._client_types import AsyncHttpxClientKwargs
from clientx._version import __version__
from clientx.decoders import (
    AsyncStreamChunksDecoder,
    AsyncStreamDecoder,
    AsyncStreamLinesDecoder,
    ModelDecoder,
    StreamDecoder,
    StreamLinesDecoder,
    StreamResponseDecoder,
    json_decoder,
)
from clientx.exceptions import (
    ArgumentValidationError,
    EndpointNameConflictError,
    EndpointSignatureError,
    UnboundResourceError,
)
from clientx.methods import get, post

pytestmark = pytest.mark.anyio


class User(BaseModel):
    id: int
    name: str


class Users(AsyncResource, prefix="/users", tags=["users"]):
    @get("/{user_id}", decoder=ModelDecoder(User))
    async def retrieve(self, user_id: int) -> User:
        """Fetch one user."""
        ...

    @post(decoder=ModelDecoder(User))
    async def create(self, json: dict[str, Any]) -> User: ...


class ExampleAPI(AsyncClientX, base_url="https://api.example.com", user_agent="example-api/1.0"):
    users = Users()

    @get("/health")
    async def health(self) -> Response: ...

    @post("/events")
    async def record(self, json: dict[str, Any]) -> None: ...

    @get("/search", decoder=json_decoder)
    async def search(self, q: Annotated[str, Query()]) -> Any: ...


def user_agent_of(client: AsyncClientX) -> str:
    return client.__clientx_client__.headers["User-Agent"]


async def test_async_endpoints_send_requests_and_decode_responses(mock_transport):
    sent: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.startswith("/users"):
            return httpx2.Response(200, json={"id": 42, "name": "Ada"})
        if request.url.path == "/search":
            return httpx2.Response(200, json={"results": [1, 2]})
        return httpx2.Response(200, text="ok")

    async with ExampleAPI(transport=mock_transport(sent, answer)) as api:
        user = await api.users.retrieve(42)
        created = await api.users.create({"name": "Ada"})
        health = await api.health()
        recorded = await api.record({"kind": "login"})
        found = await api.search("ada")

    assert user == User(id=42, name="Ada")
    assert created == User(id=42, name="Ada")
    assert isinstance(health, httpx2.Response)
    assert health.text == "ok"
    assert recorded is None
    assert found == {"results": [1, 2]}
    assert [(request.method, str(request.url)) for request in sent] == [
        ("GET", "https://api.example.com/users/42"),
        ("POST", "https://api.example.com/users"),
        ("GET", "https://api.example.com/health"),
        ("POST", "https://api.example.com/events"),
        ("GET", "https://api.example.com/search?q=ada"),
    ]
    assert sent[1].content == b'{"name":"Ada"}'
    assert {request.headers["User-Agent"] for request in sent} == {"example-api/1.0"}


async def test_async_endpoints_are_coroutine_functions():
    assert inspect.iscoroutinefunction(ExampleAPI.health)
    assert inspect.iscoroutinefunction(Users.retrieve)


async def test_calls_run_concurrently(mock_transport):
    sent: list[httpx2.Request] = []
    results: dict[int, User] = {}

    def answer(request: httpx2.Request) -> httpx2.Response:
        user_id = int(request.url.path.rsplit("/", 1)[-1])
        return httpx2.Response(200, json={"id": user_id, "name": f"user {user_id}"})

    async with ExampleAPI(transport=mock_transport(sent, answer)) as api:

        async def fetch(user_id: int) -> None:
            results[user_id] = await api.users.retrieve(user_id)

        async with anyio.create_task_group() as group:
            for user_id in (1, 2, 3):
                group.start_soon(fetch, user_id)

    assert {user_id: user.name for user_id, user in results.items()} == {1: "user 1", 2: "user 2", 3: "user 3"}
    assert len(sent) == 3


async def test_async_client_takes_the_same_options_as_clientx():
    assert user_agent_of(AsyncClientX("https://example.test")) == f"ClientX/{__version__}"
    assert user_agent_of(AsyncClientX("https://example.test", user_agent="MyApp/1.0")) == "MyApp/1.0"
    assert user_agent_of(AsyncClientX("https://example.test", headers={"User-Agent": "FromHeaders/1.0"})) == (
        "FromHeaders/1.0"
    )

    api = ExampleAPI()
    staging = ExampleAPI("https://staging.example.com", user_agent="staging/1.0")
    assert repr(api) == "ExampleAPI(base_url='https://api.example.com', user_agent='example-api/1.0')"
    assert repr(staging) == "ExampleAPI(base_url='https://staging.example.com', user_agent='staging/1.0')"
    assert isinstance(api.__clientx_client__, httpx2.AsyncClient)


async def test_an_async_client_without_a_base_url_says_how_to_set_one():
    class NoURL(AsyncClientX):
        pass

    with pytest.raises(TypeError, match=re.escape('class NoURL(AsyncClientX, base_url="https://api.example.com")')):
        NoURL()


async def test_async_with_and_aclose_close_the_connections(mock_transport):
    async with ExampleAPI(transport=mock_transport()) as api:
        assert not api.__clientx_client__.is_closed
    assert api.__clientx_client__.is_closed

    other = ExampleAPI(transport=mock_transport())
    await other.aclose()
    assert other.__clientx_client__.is_closed
    with pytest.raises(RuntimeError, match="the client has been closed"):
        await other.health()


async def test_async_with_never_swallows_an_error(mock_transport):
    with pytest.raises(ValueError, match="boom"):
        async with ExampleAPI(transport=mock_transport()):
            raise ValueError("boom")


def test_async_httpx_client_kwargs_match_httpx2_async_client_signature():
    """AsyncHttpxClientKwargs is a hand-written mirror of httpx2.AsyncClient's options; catch drift."""
    parameters = inspect.signature(httpx2.AsyncClient.__init__).parameters
    client_options = {name for name, p in parameters.items() if name != "self" and p.kind is not p.VAR_KEYWORD}
    client_options -= {"base_url"}  # AsyncClientX takes base_url as its own positional argument

    assert AsyncHttpxClientKwargs.__required_keys__ == frozenset()
    assert set(AsyncHttpxClientKwargs.__optional_keys__) == client_options


async def test_an_error_status_raises_with_the_body_read(mock_transport):
    async with ExampleAPI(transport=mock_transport(status=404, json={"error": "not found"})) as api:
        with pytest.raises(httpx2.HTTPStatusError) as caught:
            await api.users.retrieve(1000)

    assert caught.value.response.status_code == 404
    assert caught.value.response.json() == {"error": "not found"}


async def test_raise_for_status_can_be_turned_off(mock_transport):
    class Lenient(AsyncClientX):
        @get("/files/{name}", raise_for_status=False)
        async def file(self, name: str) -> Response: ...

        @get("/strict/{name}")
        async def strict(self, name: str) -> Response: ...

    async with Lenient("https://api.example.com", transport=mock_transport(status=404)) as api:
        assert (await api.file("a.txt")).status_code == 404
        with pytest.raises(httpx2.HTTPStatusError):
            await api.strict("a.txt")

    async with Lenient("https://api.example.com", transport=mock_transport(status=404), raise_for_status=False) as api:
        assert (await api.strict("a.txt")).status_code == 404


class TrackedAsyncStream(httpx2.AsyncByteStream):
    """A response body that arrives line by line, and records whether it was closed."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for line in self.body.splitlines(keepends=True):
            yield line

    async def aclose(self) -> None:
        self.closed = True


class Downloads(AsyncClientX):
    @get("/export", decoder=StreamResponseDecoder())
    async def export(self) -> Response: ...


async def test_a_streamed_response_is_handed_over_open(mock_transport):
    stream = TrackedAsyncStream(b"line 1\nline 2\n")
    transport = mock_transport(handler=lambda request: httpx2.Response(200, stream=stream))

    async with Downloads("https://api.example.com", transport=transport) as api:
        response = await api.export()
        assert not stream.closed
        assert [line async for line in response.aiter_lines()] == ["line 1", "line 2"]
        await response.aclose()

    assert stream.closed


async def test_a_streamed_error_response_is_read_and_closed_before_raising(mock_transport):
    stream = TrackedAsyncStream(b"broken")
    transport = mock_transport(handler=lambda request: httpx2.Response(500, stream=stream))

    async with Downloads("https://api.example.com", transport=transport) as api:
        with pytest.raises(httpx2.HTTPStatusError) as caught:
            await api.export()

    assert stream.closed
    assert caught.value.response.text == "broken"


async def test_arguments_are_validated_before_sending(mock_transport):
    class Search(AsyncClientX):
        @get("/search")
        async def search(self, page: Annotated[int, Query(), Field(ge=1)]) -> Response: ...

    sent: list[httpx2.Request] = []
    async with Search("https://api.example.com", transport=mock_transport(sent), validate_arguments=True) as api:
        with pytest.raises(ArgumentValidationError) as caught:
            await api.search(0)

    assert caught.value.parameter == "page"
    assert sent == []


async def test_deprecated_endpoints_warn_and_timeouts_reach_the_request(mock_transport):
    class Legacy(AsyncClientX):
        @get("/v1/old", deprecated=DeprecatedMessage("Use new() instead."), timeout=2.5)
        async def old(self) -> None: ...

    sent: list[httpx2.Request] = []
    async with Legacy("https://api.example.com", transport=mock_transport(sent)) as api:
        with pytest.warns(DeprecationWarning, match=r"Use new\(\) instead\."):
            await api.old()

    assert sent[0].extensions["timeout"] == httpx2.Timeout(2.5).as_dict()


def clientx_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "clientx"]


async def test_calls_are_logged_like_sync_calls(caplog, mock_transport):
    caplog.set_level(logging.DEBUG, logger="clientx")

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    async with ExampleAPI(transport=mock_transport(json={"id": 1, "name": "Ada"})) as api:
        await api.users.retrieve(1)
    async with ExampleAPI(transport=mock_transport(status=404)) as api:
        with pytest.raises(httpx2.HTTPStatusError):
            await api.users.retrieve(2)
    async with ExampleAPI(transport=mock_transport(handler=refuse)) as api:
        with pytest.raises(httpx2.ConnectError):
            await api.users.retrieve(3)

    messages = [record.getMessage() for record in clientx_records(caplog)]
    assert len(messages) == 3
    assert re.fullmatch(r"ClientX request: GET /users/1 -> 200 in \d+\.\d ms \(Users\.retrieve\)", messages[0])
    assert re.fullmatch(
        r"ClientX request: GET /users/2 -> 404 HTTPStatusError in \d+\.\d ms \(Users\.retrieve\)", messages[1]
    )
    assert re.fullmatch(r"ClientX request: GET /users/3 -> ConnectError in \d+\.\d ms \(Users\.retrieve\)", messages[2])


async def test_async_resources_nest_and_keep_their_prefix_and_tags(endpoint_of, mock_transport):
    class Members(AsyncResource, prefix="/teams/{team_id}/members", tags=["members"]):
        @get()
        async def list_members(self, team_id: int) -> Response: ...

    class Teams(AsyncResource, prefix="/teams", tags=["teams"]):
        members = Members()

        @get("/{team_id}")
        async def retrieve(self, team_id: int) -> Response: ...

    class TeamsAPI(AsyncClientX):
        teams = Teams()

    sent: list[httpx2.Request] = []
    async with TeamsAPI("https://api.example.com", transport=mock_transport(sent)) as api:
        await api.teams.retrieve(7)
        await api.teams.members.list_members(7)

    assert [request.url.path for request in sent] == ["/teams/7", "/teams/7/members"]
    assert endpoint_of(Teams.retrieve).tags == ["teams"]
    assert endpoint_of(Members.list_members).tags == ["members"]


async def test_an_unmounted_async_resource_raises():
    with pytest.raises(UnboundResourceError, match="Resource 'Users' isn't mounted on a client"):
        await Users().retrieve(1)


async def test_an_async_endpoint_called_on_something_else_raises():
    with pytest.raises(
        TypeError, match="`async def` endpoints must be called on an AsyncClientX instance or a Resource mounted on one"
    ):
        await ExampleAPI.health(object())  # pyright: ignore[reportArgumentType]


def test_an_async_endpoint_on_a_sync_client_or_resource_raises():
    with pytest.raises(EndpointSignatureError, match=r"is `async def`, so it can't be an endpoint of '.*SyncAPI'"):

        class SyncAPI(ClientX):
            @get("/health")  # type: ignore[type-var]  # pyright: ignore[reportArgumentType, reportCallIssue, reportUntypedFunctionDecorator]
            async def health(self) -> Response: ...

    with pytest.raises(
        EndpointSignatureError, match="a Resource subclass. Define it with `def`, or subclass AsyncResource"
    ):

        class SyncUsers(Resource):
            @get("/users")  # type: ignore[type-var]  # pyright: ignore[reportArgumentType, reportCallIssue, reportUntypedFunctionDecorator]
            async def list_users(self) -> Response: ...


def test_a_sync_endpoint_on_an_async_client_or_resource_raises():
    with pytest.raises(EndpointSignatureError, match=r"is a plain `def`, so it can't be an endpoint of '.*AsyncAPI'"):

        class AsyncAPI(AsyncClientX):
            @get("/health")  # type: ignore[type-var]  # pyright: ignore[reportArgumentType, reportCallIssue, reportUntypedFunctionDecorator]
            def health(self) -> Response: ...

    with pytest.raises(
        EndpointSignatureError, match="an AsyncResource subclass. Define it with `async def`, or subclass Resource"
    ):

        class AsyncUsers(AsyncResource):
            @get("/users")  # type: ignore[type-var]  # pyright: ignore[reportArgumentType, reportCallIssue, reportUntypedFunctionDecorator]
            def list_users(self) -> Response: ...


def test_a_resource_mounts_only_on_its_own_kind():
    class SyncUsers(Resource):
        @get("/users")
        def list_users(self) -> Response: ...

    with pytest.raises(TypeError, match="For an AsyncClientX, subclass AsyncResource instead"):

        class AsyncAPI(AsyncClientX):
            users = SyncUsers()

    with pytest.raises(TypeError, match="For a ClientX, subclass Resource instead"):

        class SyncAPI(ClientX):
            users = Users()

    with pytest.raises(TypeError, match="can only be mounted on an AsyncClientX or AsyncResource subclass") as caught:

        class NotAClient:
            users = Users()

    assert "instead" not in str(caught.value)  # no hint about the other kind: it isn't a client at all


def test_a_class_cant_be_both_sync_and_async():
    with pytest.raises(TypeError, match="can't subclass both ClientX and AsyncClientX"):

        class Both(ClientX, AsyncClientX):  # pyright: ignore[reportGeneralTypeIssues]
            pass

    with pytest.raises(TypeError, match="can't subclass both Resource and AsyncResource"):

        class BothResources(Resource, AsyncResource):
            pass


class JSONLinesDecoder(AsyncStreamDecoder[dict[str, Any]]):
    async def __call__(self, response: httpx2.Response) -> AsyncIterator[dict[str, Any]]:
        async for line in response.aiter_lines():
            if line:
                yield json.loads(line)


class FailsMidway(AsyncStreamDecoder[str]):
    async def __call__(self, response: httpx2.Response) -> AsyncIterator[str]:
        yield "first"
        raise ValueError("bad line")


class FailsAtOnce(AsyncStreamDecoder[str]):
    def __call__(self, response: httpx2.Response) -> AsyncIterator[str]:
        raise ValueError("can't decode")


class SyncHeaderDecoder(StreamDecoder[str]):
    def __call__(self, response: httpx2.Response) -> Iterator[str]:
        yield response.headers["x-id"]


class Events(AsyncClientX):
    @get("/events", decoder=AsyncStreamLinesDecoder())
    async def events(self) -> AsyncIterator[str]: ...

    @get("/download", decoder=AsyncStreamChunksDecoder(chunk_size=4))
    async def download(self) -> AsyncIterator[bytes]: ...

    @get("/records", decoder=JSONLinesDecoder())
    async def records(self) -> AsyncIterator[dict[str, Any]]: ...

    @get("/midway", decoder=FailsMidway())
    async def midway(self) -> AsyncIterator[str]: ...

    @get("/at-once", decoder=FailsAtOnce())
    async def at_once(self) -> AsyncIterator[str]: ...


def streaming(body: bytes, status: int = 200) -> tuple[TrackedAsyncStream, Callable[[httpx2.Request], httpx2.Response]]:
    stream = TrackedAsyncStream(body)
    return stream, lambda request: httpx2.Response(status, stream=stream)


async def test_async_stream_decoders_yield_as_the_body_arrives_and_close_at_the_end(mock_transport):
    stream, handler = streaming(b"line 1\nline 2\n")
    async with Events("https://api.example.com", transport=mock_transport(handler=handler)) as api:
        lines = await api.events()
        assert not stream.closed
        assert [line async for line in lines] == ["line 1", "line 2"]
        assert stream.closed

    stream, handler = streaming(b"abcdefghij")
    async with Events("https://api.example.com", transport=mock_transport(handler=handler)) as api:
        assert [chunk async for chunk in await api.download()] == [b"abcd", b"efgh", b"ij"]
        assert stream.closed

    stream, handler = streaming(b'{"id": 1}\n\n{"id": 2}\n')
    async with Events("https://api.example.com", transport=mock_transport(handler=handler)) as api:
        assert [record async for record in await api.records()] == [{"id": 1}, {"id": 2}]
        assert stream.closed


async def test_stopping_early_closes_the_response_when_the_iterator_is_closed_or_collected(mock_transport):
    stream, handler = streaming(b"line 1\nline 2\nline 3\n")
    async with Events("https://api.example.com", transport=mock_transport(handler=handler)) as api:
        lines = await api.events()
        assert await anext(lines) == "line 1"
        # The iterator is an async generator, though its declared type is AsyncIterator[str].
        await cast(AsyncGenerator[str, None], lines).aclose()
        assert stream.closed

    stream, handler = streaming(b"line 1\nline 2\nline 3\n")
    async with Events("https://api.example.com", transport=mock_transport(handler=handler)) as api:
        async for line in await api.events():
            assert line == "line 1"
            break
        # The loop dropped the iterator: the event loop closes it once it's garbage-collected.
        gc.collect()
        for _ in range(3):
            await anyio.sleep(0)
        assert stream.closed


async def test_a_decoder_that_fails_closes_the_response(mock_transport):
    stream, handler = streaming(b"anything\n")
    async with Events("https://api.example.com", transport=mock_transport(handler=handler)) as api:
        items = await api.midway()
        with pytest.raises(ValueError, match="bad line"):
            assert [item async for item in items] == ["first"]
        assert stream.closed

    stream, handler = streaming(b"anything\n")
    async with Events("https://api.example.com", transport=mock_transport(handler=handler)) as api:
        with pytest.raises(ValueError, match="can't decode"):
            await api.at_once()
        assert stream.closed


async def test_an_error_status_raises_before_streaming(mock_transport):
    stream, handler = streaming(b"server error", status=500)
    async with Events("https://api.example.com", transport=mock_transport(handler=handler)) as api:
        with pytest.raises(httpx2.HTTPStatusError) as caught:
            await api.events()

    assert stream.closed
    assert caught.value.response.text == "server error"


async def test_a_streamed_call_is_logged_as_streamed(caplog, mock_transport):
    caplog.set_level(logging.DEBUG, logger="clientx")
    _, handler = streaming(b"line\n")
    async with Events("https://api.example.com", transport=mock_transport(handler=handler)) as api:
        assert [line async for line in await api.events()] == ["line"]

    [record] = clientx_records(caplog)
    assert record.__dict__["clientx_stream"] is True


def test_a_stream_decoder_must_match_the_endpoint_kind():
    with pytest.raises(
        EndpointSignatureError,
        match="StreamLinesDecoder, streams synchronously, for `def` endpoints. Use AsyncStreamLinesDecoder",
    ):

        class SyncLines(AsyncClientX):
            @get("/events", decoder=StreamLinesDecoder())
            async def events(self) -> Iterator[str]: ...

    with pytest.raises(
        EndpointSignatureError,
        match="SyncHeaderDecoder, streams synchronously, for `def` endpoints. Use an AsyncStreamDecoder subclass",
    ):

        class SyncCustom(AsyncClientX):
            @get("/events", decoder=SyncHeaderDecoder())
            async def events(self) -> Iterator[str]: ...

    with pytest.raises(
        EndpointSignatureError,
        match="AsyncStreamChunksDecoder, streams asynchronously, for `async def` endpoints. Use StreamChunksDecoder",
    ):

        class AsyncChunks(ClientX):
            @get("/download", decoder=AsyncStreamChunksDecoder())
            def download(self) -> AsyncIterator[bytes]: ...

    with pytest.raises(
        EndpointSignatureError,
        match="JSONLinesDecoder, streams asynchronously, for `async def` endpoints. Use a StreamDecoder subclass",
    ):

        class AsyncCustom(ClientX):
            @get("/records", decoder=JSONLinesDecoder())
            def records(self) -> AsyncIterator[dict[str, Any]]: ...


@pytest.mark.parametrize("name", ["aclose", "__aenter__", "__aexit__", "__clientx_client__"])
def test_an_async_endpoint_cant_use_a_name_async_clientx_already_uses(name: str):
    namespace: dict[str, Callable[..., Any]] = {}

    async def endpoint(self: AsyncClientX) -> Response: ...

    namespace[name] = get("/x")(endpoint)
    with pytest.raises(EndpointNameConflictError, match="AsyncClientX already uses that name"):
        type("Conflicting", (AsyncClientX,), namespace)


async def test_close_is_free_for_an_endpoint_on_an_async_client(mock_transport):
    class Sessions(AsyncClientX):
        @post("/sessions/close")
        async def close(self) -> None: ...

    sent: list[httpx2.Request] = []
    async with Sessions("https://api.example.com", transport=mock_transport(sent)) as api:
        await api.close()

    assert [request.url.path for request in sent] == ["/sessions/close"]
