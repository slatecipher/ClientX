import logging
from collections.abc import Callable, Iterator

import httpx2
import pytest
from pydantic import BaseModel

from clientx import ClientX, Resource, Response
from clientx.decoders import ModelDecoder, StreamLinesDecoder
from clientx.exceptions import EndpointNameConflictError, MissingPathArgumentsError, UnboundResourceError
from clientx.methods import get, post


class User(BaseModel):
    id: int
    name: str


class Users(Resource, prefix="/users", tags=["users"]):
    @get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: int) -> User: ...

    @post("")
    def create(self, json: dict[str, str]) -> Response: ...

    # `send` and `client` would clash on a ClientX, but are free on a resource.
    @post("/{user_id}/messages")
    def send(self, user_id: int, json: dict[str, str]) -> Response: ...

    @get("/{user_id}/client")
    def client(self, user_id: int) -> Response: ...


class Issues(Resource, prefix="/repos/{owner}/{repo}/issues"):
    @get("/{number}")
    def retrieve(self, owner: str, repo: str, number: int) -> Response: ...


class Repos(Resource, prefix="/repos/{owner}/{repo}"):
    issues = Issues()

    @get("")
    def retrieve(self, owner: str, repo: str) -> Response: ...


class ExampleAPI(ClientX):
    users = Users()
    repos = Repos()


@pytest.fixture
def make_api(mock_transport) -> Callable[[list[httpx2.Request]], ExampleAPI]:
    def make(sent: list[httpx2.Request]) -> ExampleAPI:
        return ExampleAPI(
            "https://api.example.com",
            user_agent="tests/1.0",
            transport=mock_transport(sent, json={"id": 42, "name": "Ada"}),
        )

    return make


def paths(sent: list[httpx2.Request]) -> list[str]:
    return [f"{request.method} {request.url.path}" for request in sent]


def test_resource_endpoint_sends_through_the_clients_connection(make_api):
    sent: list[httpx2.Request] = []

    user = make_api(sent).users.retrieve(42)

    assert user == User(id=42, name="Ada")
    assert str(sent[0].url) == "https://api.example.com/users/42"
    assert sent[0].headers["User-Agent"] == "tests/1.0"


def test_endpoint_with_an_empty_path_uses_the_prefix(make_api):
    sent: list[httpx2.Request] = []

    make_api(sent).users.create({"name": "Ada"})

    assert paths(sent) == ["POST /users"]
    assert sent[0].content == b'{"name":"Ada"}'


def test_names_reserved_on_clientx_are_free_on_a_resource(make_api):
    sent: list[httpx2.Request] = []
    api = make_api(sent)

    api.users.send(42, {"text": "hi"})
    api.users.client(42)

    assert paths(sent) == ["POST /users/42/messages", "GET /users/42/client"]


def test_prefix_placeholders_are_filled_from_the_method_arguments(make_api):
    sent: list[httpx2.Request] = []

    make_api(sent).repos.retrieve("octo", "hello")

    assert paths(sent) == ["GET /repos/octo/hello"]


def test_nested_resources_send_through_the_root_client(make_api):
    sent: list[httpx2.Request] = []

    make_api(sent).repos.issues.retrieve("octo", "hello", 5)

    assert paths(sent) == ["GET /repos/octo/hello/issues/5"]
    assert sent[0].headers["User-Agent"] == "tests/1.0"


def test_each_client_instance_binds_its_own_resource(make_api):
    first: list[httpx2.Request] = []
    second: list[httpx2.Request] = []

    make_api(first).users.retrieve(1)
    make_api(second).users.retrieve(2)

    assert paths(first) == ["GET /users/1"]
    assert paths(second) == ["GET /users/2"]


def test_streamed_resource_endpoint_yields_items():
    class Events(Resource, prefix="/events"):
        @get("", decoder=StreamLinesDecoder())
        def stream(self) -> Iterator[str]: ...

    class EventsAPI(ClientX):
        events = Events()

    api = EventsAPI(
        "https://api.example.com", transport=httpx2.MockTransport(lambda r: httpx2.Response(200, text="a\nb"))
    )

    assert list(api.events.stream()) == ["a", "b"]


def test_class_access_returns_the_unbound_resource():
    assert isinstance(ExampleAPI.users, Users)
    assert repr(ExampleAPI.users) == "Users(prefix='/users')"


@pytest.mark.parametrize("resource", [Users(), ExampleAPI.users], ids=["new instance", "class attribute"])
def test_calling_an_unmounted_resource_raises(resource: Users):
    with pytest.raises(UnboundResourceError, match="Resource 'Users' isn't mounted on a client"):
        resource.retrieve(1)


def test_calling_an_endpoint_on_something_other_than_a_client_raises():
    class PlainAPI(ClientX):
        @get("/health")
        def health(self) -> Response: ...

    with pytest.raises(TypeError, match="must be called on a ClientX instance or a mounted Resource, not on 'object'"):
        PlainAPI.health(object())  # pyright: ignore[reportArgumentType]


def test_endpoints_get_full_paths_and_resource_tags_first(endpoint_of):
    class Teams(Resource, prefix="/teams", tags=["teams", "read"]):
        @get("/{team_id}", tags=["read", "detail"])
        def retrieve(self, team_id: int) -> Response: ...

    endpoint = endpoint_of(Teams.retrieve)
    assert str(endpoint.path) == "/teams/{team_id}"
    assert endpoint.tags == ["teams", "read", "detail"]


@pytest.mark.parametrize(
    ("prefix", "path", "expected"),
    [
        ("/users", "/{user_id}", "/users/{user_id}"),
        ("/users/", "/{user_id}", "/users/{user_id}"),
        ("/users", "{user_id}", "/users/{user_id}"),
        ("/users", "", "/users"),
        ("/users", "/", "/users/"),
        ("", "/health", "/health"),
    ],
)
def test_prefix_and_path_are_joined_with_one_slash(prefix: str, path: str, expected: str, endpoint_of):
    class Things(Resource, prefix=prefix):
        @get(path)
        def call(self, user_id: int = 0) -> Response: ...

    endpoint = endpoint_of(Things.call)
    assert str(endpoint.path) == expected


def test_subclasses_keep_the_parent_prefix_and_tags_unless_they_set_their_own(endpoint_of):
    class Base(Resource, prefix="/base", tags=["base"]):
        @get("/a")
        def a(self) -> Response: ...

    class Child(Base):
        @get("/b")
        def b(self) -> Response: ...

    class Other(Base, prefix="/other", tags=["other"]):
        @get("/c")
        def c(self) -> Response: ...

    found = {
        name: (str(endpoint.path), endpoint.tags)
        for name, endpoint in (("a", endpoint_of(Base.a)), ("b", endpoint_of(Child.b)), ("c", endpoint_of(Other.c)))
    }
    assert found == {
        "a": ("/base/a", ["base"]),
        "b": ("/base/b", ["base"]),
        "c": ("/other/c", ["other"]),
    }


def test_mounting_on_a_class_that_is_not_a_client_or_resource_raises():
    with pytest.raises(
        TypeError, match=r"can only be mounted on a ClientX or Resource subclass, not on '[\w.<>]*NotAClient'"
    ):

        class NotAClient:
            users = Users()


def test_resource_mounted_under_a_name_clientx_uses_raises():
    with pytest.raises(EndpointNameConflictError, match=r"BrokenAPI\.client' .* ClientX already uses that name"):

        class BrokenAPI(ClientX):
            client = Users()  # pyright: ignore[reportAssignmentType]


@pytest.mark.parametrize("name", ["__get__", "__clientx_parent__"])
def test_resource_endpoint_cannot_use_a_name_resource_uses(name: str):
    def endpoint(self: Resource) -> Response: ...

    endpoint.__name__ = endpoint.__qualname__ = name

    with pytest.raises(EndpointNameConflictError, match="Resource already uses that name"):
        type("Dynamic", (Resource,), {name: get("/x")(endpoint)})


def test_resource_calls_are_logged_with_the_resource_endpoint_name(caplog, make_api):
    caplog.set_level(logging.DEBUG, logger="clientx")

    make_api([]).users.retrieve(42)

    [record] = [record for record in caplog.records if record.name == "clientx"]
    assert record.__dict__["clientx_endpoint"] == "Users.retrieve"
    assert record.__dict__["clientx_path"] == "/users/42"


def test_a_prefix_placeholder_without_a_parameter_raises_when_the_resource_is_defined():
    with pytest.raises(MissingPathArgumentsError, match=r"'/repos/\{owner\}/items': owner"):

        class Items(Resource, prefix="/repos/{owner}"):  # pyright: ignore[reportUnusedClass]
            @get("/items")
            def list_items(self) -> Response: ...
