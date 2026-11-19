"""Clients and resources: setup, class-body rules, and settings."""

import inspect
import re
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

import clientx
from clientx import AsyncClientX, AsyncResource, ClientX, DefinitionError, Resource, method
from clientx._registry import endpoint_for
from clientx._types import AsyncHttpxClientOptions, BuildRequestKwargs, HttpxClientOptions

type MockTransport = Callable[..., httpx2.MockTransport]

BASE_URL = "https://api.example.com"


def only_request(sent: list[httpx2.Request]) -> httpx2.Request:
    (request,) = sent
    return request


# Clients


def test_a_client_sends_through_its_own_connection(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/health")
        def health(self) -> None: ...

    sent: list[httpx2.Request] = []
    with API(BASE_URL, transport=mock_transport(sent)) as api:
        assert isinstance(api, httpx2.Client)
        api.health()
    assert api.is_closed
    assert str(only_request(sent).url) == "https://api.example.com/health"


def test_the_base_url_comes_from_the_argument_then_the_class(mock_transport: MockTransport) -> None:
    class API(ClientX, base_url="https://api.example.com/v1"):
        @method.get("/health")
        def health(self) -> None: ...

    class Child(API): ...

    class Staging(API, base_url="https://staging.example.com"): ...

    sent: list[httpx2.Request] = []
    transport = mock_transport(sent)
    API(transport=transport).health()
    Child(transport=transport).health()
    Staging(transport=transport).health()
    API("https://localhost:8000", transport=transport).health()
    assert [str(request.url) for request in sent] == [
        "https://api.example.com/v1/health",
        "https://api.example.com/v1/health",
        "https://staging.example.com/health",
        "https://localhost:8000/health",
    ]


@pytest.mark.parametrize("base", [ClientX, AsyncClientX])
def test_a_client_without_a_base_url_fails(base: type) -> None:
    api_class = type("API", (base,), {})
    message = f'or set it in the class statement, as in class API({base.__name__}, base_url="https://api.example.com")'
    with pytest.raises(TypeError, match=re.escape(message)):
        api_class()


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        pytest.param("api.example.com", "which needs a scheme and a host", id="no scheme"),
        pytest.param("http://[::1", "which isn't a URL", id="not a URL"),
    ],
)
def test_a_class_base_url_must_be_an_absolute_url(base_url: str, message: str) -> None:
    with pytest.raises(DefinitionError, match=re.escape(f"'API' has base_url={base_url!r}, {message}")):
        type("API", (ClientX,), {}, base_url=base_url)


def test_the_user_agent_comes_from_the_argument_then_headers_then_the_class(mock_transport: MockTransport) -> None:
    class API(ClientX, user_agent="ExampleAPI/1.0"):
        @method.get("/health")
        def health(self) -> None: ...

    class Child(API): ...

    def user_agent(api: ClientX) -> str:
        return api.headers["User-Agent"]

    transport = mock_transport()
    assert user_agent(API(BASE_URL, transport=transport, user_agent="Explicit/2")) == "Explicit/2"
    assert user_agent(API(BASE_URL, transport=transport, headers={"User-Agent": "FromHeaders/3"})) == "FromHeaders/3"
    assert user_agent(API(BASE_URL, transport=transport)) == "ExampleAPI/1.0"
    assert user_agent(Child(BASE_URL, transport=transport)) == "ExampleAPI/1.0"

    class Plain(ClientX): ...

    assert user_agent(Plain(BASE_URL, transport=transport)) == f"ClientX/{clientx.__version__}"


def test_the_user_agent_is_sent(mock_transport: MockTransport) -> None:
    class API(ClientX, user_agent="ExampleAPI/1.0"):
        @method.get("/health")
        def health(self) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).health()
    assert only_request(sent).headers["User-Agent"] == "ExampleAPI/1.0"


def test_a_clients_repr_shows_its_base_url_and_user_agent(mock_transport: MockTransport) -> None:
    class ExampleAPI(ClientX, user_agent="ExampleAPI/1.0"): ...

    class AsyncAPI(AsyncClientX): ...

    transport = mock_transport()
    assert repr(ExampleAPI("https://user:s3cret@api.example.com/v1", transport=transport)) == (
        "test_a_clients_repr_shows_its_base_url_and_user_agent.<locals>.ExampleAPI("
        "base_url='https://user:[redacted]@api.example.com/v1/', user_agent='ExampleAPI/1.0')"
    )
    assert "base_url='https://user@api.example.com'" in repr(ExampleAPI("https://user@api.example.com"))
    assert f"user_agent='ClientX/{clientx.__version__}'" in repr(AsyncAPI(BASE_URL))


def test_a_class_cant_be_both_kinds_of_client() -> None:
    # Built with type(): type checkers already reject the class statement.
    with pytest.raises(DefinitionError, match="can't subclass both ClientX and AsyncClientX: choose one"):
        type("Both", (ClientX, AsyncClientX), {})


@pytest.mark.parametrize("name", ["send", "headers"])
def test_an_endpoint_cant_use_a_name_the_client_uses(name: str) -> None:
    def endpoint(self: ClientX) -> None: ...

    with pytest.raises(DefinitionError, match=re.escape(f"can't be named '{name}': ClientX already uses that name")):
        type("API", (ClientX,), {name: method.get("/x")(endpoint)})


def test_a_mounted_resource_cant_use_a_name_the_client_uses() -> None:
    class Users(Resource, prefix="/users"): ...

    with pytest.raises(DefinitionError, match="put it on a Resource mounted on the client"):
        type("API", (ClientX,), {"headers": Users()})


def test_a_clients_names_are_free_on_a_resource(mock_transport: MockTransport) -> None:
    class Messages(Resource, prefix="/messages"):
        @method.post("/send")
        def send(self) -> None: ...

        @method.get("/{message_id}")
        def get(self, message_id: int) -> None: ...

    class API(ClientX):
        messages = Messages()

    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent))
    api.messages.send()
    api.messages.get(1)
    assert [request.url.path for request in sent] == ["/messages/send", "/messages/1"]


@pytest.mark.parametrize(
    ("base", "kind"),
    [(ClientX, "`async def`"), (AsyncClientX, "a plain `def`")],
    ids=["async def on ClientX", "def on AsyncClientX"],
)
def test_an_endpoint_must_be_the_clients_kind(base: type, kind: str) -> None:
    async def asynchronous(self: object) -> None: ...

    def synchronous(self: object) -> None: ...

    function = asynchronous if base is ClientX else synchronous
    with pytest.raises(DefinitionError, match=re.escape(f"is {kind}, so it can't be an endpoint of")):
        type("API", (base,), {"ping": method.get("/ping")(function)})


# Resources


def test_a_prefix_is_joined_with_one_slash(mock_transport: MockTransport) -> None:
    class Users(Resource, prefix="/users/"):
        @method.get("/active")
        def active(self) -> None: ...

        @method.get()
        def everyone(self) -> None: ...

    class API(ClientX):
        users = Users()

    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent))
    api.users.active()
    api.users.everyone()
    # An endpoint without a path of its own calls the prefix as it's written.
    assert [request.url.path for request in sent] == ["/users/active", "/users/"]


def test_resources_nest_and_their_prefixes_dont_compose(mock_transport: MockTransport) -> None:
    class Keys(Resource, prefix="/keys"):
        @method.get("/{key_id}")
        def fetch(self, key_id: str) -> None: ...

    class Users(Resource, prefix="/users"):
        keys = Keys()

    class API(ClientX):
        users = Users()

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).users.keys.fetch("k1")
    assert only_request(sent).url.path == "/keys/k1"


def test_a_resource_subclass_keeps_its_parents_prefix(mock_transport: MockTransport) -> None:
    class Users(Resource, prefix="/users"): ...

    class Admins(Users):
        @method.get("/admins")
        def admins(self) -> None: ...

    class API(ClientX):
        admins = Admins()

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).admins.admins()
    assert only_request(sent).url.path == "/users/admins"


def test_an_endpoint_with_a_second_name_gets_the_prefix_once(mock_transport: MockTransport) -> None:
    class Users(Resource, prefix="/users"):
        @method.get("/active")
        def active(self) -> None: ...

        current = active

    class API(ClientX):
        users = Users()

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).users.current()
    assert only_request(sent).url.path == "/users/active"


def test_an_endpoint_belongs_to_one_class() -> None:
    class Users(Resource, prefix="/users"):
        @method.get("/active")
        def active(self) -> None: ...

    with pytest.raises(DefinitionError, match="belongs to 'test_an_endpoint_belongs_to_one_class.<locals>.Users'"):

        class Admins(Resource, prefix="/admins"):
            active = Users.active


def test_a_resource_on_its_class_is_unbound_and_on_a_client_is_bound(mock_transport: MockTransport) -> None:
    class Users(Resource, prefix="/users"): ...

    class API(ClientX):
        users = Users()

    api = API(BASE_URL, transport=mock_transport())
    assert API.users.__clientx_parent__ is None
    assert api.users.__clientx_parent__ is api
    assert api.users is not API.users
    assert (
        repr(api.users)
        == "test_a_resource_on_its_class_is_unbound_and_on_a_client_is_bound.<locals>.Users(prefix='/users')"
    )


def test_an_endpoint_on_an_unmounted_resource_cant_be_called() -> None:
    class Users(Resource, prefix="/users"):
        @method.get("/active")
        def active(self) -> None: ...

    with pytest.raises(DefinitionError, match=re.escape("isn't mounted on a client. Mount an instance")):
        Users().active()


def test_an_endpoint_must_be_called_on_a_client(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/health")
        def health(self) -> None: ...

    with pytest.raises(DefinitionError, match="must be called on an instance of ClientX or a resource mounted on one"):
        API.health(object())  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]


def test_a_class_cant_be_both_kinds_of_resource() -> None:
    with pytest.raises(DefinitionError, match="can't subclass both Resource and AsyncResource: choose one"):
        type("Both", (Resource, AsyncResource), {})


@pytest.mark.parametrize(
    ("resource", "owner", "message"),
    [
        (Resource, AsyncClientX, "can only be mounted on a ClientX or Resource subclass"),
        (Resource, object, "can only be mounted on a ClientX or Resource subclass, not on 'Owner'."),
    ],
    ids=["Resource on AsyncClientX", "Resource on a plain class"],
)
def test_a_resource_is_mounted_on_its_own_kind(resource: type, owner: type, message: str) -> None:
    users = type("Users", (resource,), {})()
    with pytest.raises(DefinitionError, match=re.escape(message)):
        type("Owner", (owner,), {"users": users})


@pytest.mark.anyio
async def test_async_resources_send_through_the_async_client(mock_transport: MockTransport) -> None:
    class Users(AsyncResource, prefix="/users"):
        @method.get("/{user_id}")
        async def fetch(self, user_id: int) -> None: ...

    class API(AsyncClientX):
        users = Users()

    sent: list[httpx2.Request] = []
    async with API(BASE_URL, transport=mock_transport(sent)) as api:
        await api.users.fetch(1)
    assert only_request(sent).url.path == "/users/1"


def test_a_resource_class_must_be_mounted_as_an_instance() -> None:
    class Users(Resource, prefix="/users"):
        @method.get("/{user_id}")
        def retrieve(self, user_id: int) -> None: ...

    class Issues(AsyncResource, prefix="/issues"):
        @method.get()
        async def list_issues(self) -> None: ...

    message = re.escape("isn't mounted. Mount an instance: users = Users().")
    with pytest.raises(DefinitionError, match=message):

        class API(ClientX):
            users = Users

    with pytest.raises(DefinitionError, match=message):

        class Teams(Resource):
            users = Users

    with pytest.raises(DefinitionError, match=re.escape("Mount an instance: issues = Issues().")):

        class AsyncAPI(AsyncClientX):
            issues = Issues


def test_a_resource_class_defined_in_a_body_can_be_mounted_there(mock_transport: MockTransport) -> None:
    class API(ClientX):
        class Users(Resource, prefix="/users"):
            @method.get("/{user_id}")
            def retrieve(self, user_id: int) -> None: ...

        users = Users()

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).users.retrieve(1)
    assert only_request(sent).url.path == "/users/1"


# Tags: nothing reads them yet, so the tests read each endpoint's directly.


def tags_of(function: object) -> list[str]:
    endpoint = endpoint_for(function)
    assert endpoint is not None
    return endpoint.tags


def test_an_endpoint_keeps_each_tag_once_in_order() -> None:
    class API(ClientX):
        @method.get("/health", tags=["ops", "public", "ops"])
        def health(self) -> None: ...

        @method.get("/version")
        def version(self) -> None: ...

    assert (tags_of(API.health), tags_of(API.version)) == (["ops", "public"], [])


def test_a_resources_tags_go_before_its_endpoints_own() -> None:
    class Users(Resource, tags=["users", "public"]):
        @method.get("/users", tags=["public", "read"])
        def list_users(self) -> None: ...

    assert tags_of(Users.list_users) == ["users", "public", "read"]


def test_a_resource_subclass_adds_its_tags_to_its_parents() -> None:
    class Users(Resource, tags=["users"]):
        @method.get("/users/{user_id}")
        def retrieve(self, user_id: int) -> None: ...

    class Admins(Users, tags=["admin", "users"]):
        @method.post("/admins", tags=["write"])
        def create(self) -> None: ...

    class Guests(Users):
        @method.get("/guests")
        def list_guests(self) -> None: ...

    assert tags_of(Admins.create) == ["users", "admin", "write"]
    assert tags_of(Guests.list_guests) == ["users"]
    # An inherited endpoint keeps the tags of the class that declares it.
    assert tags_of(Admins.retrieve) == ["users"]


def test_a_mounted_resource_keeps_its_own_tags() -> None:
    class Issues(AsyncResource, tags=["issues"]):
        @method.get("/issues")
        async def list_issues(self) -> None: ...

    class Repos(AsyncResource, tags=["repos"]):
        issues = Issues()

    assert isinstance(Repos.issues, Issues)
    assert tags_of(Issues.list_issues) == ["issues"]


# The TypedDicts that mirror httpx2's signatures


@pytest.mark.parametrize(
    ("typed_dict", "function", "passed_separately"),
    [
        (HttpxClientOptions, httpx2.Client.__init__, {"base_url"}),
        (AsyncHttpxClientOptions, httpx2.AsyncClient.__init__, {"base_url"}),
        (BuildRequestKwargs, httpx2.Client.build_request, {"method", "url"}),
    ],
    ids=["Client options", "AsyncClient options", "build_request arguments"],
)
def test_a_typed_dict_lists_every_parameter_of_its_httpx2_function(
    typed_dict: Any, function: Callable[..., object], passed_separately: set[str]
) -> None:
    # If httpx2 adds a parameter, add it to the TypedDict. If only CI's
    # test-lowest job fails, a key we list is newer than the lowest httpx2
    # version pyproject.toml allows.
    parameters = inspect.signature(function).parameters.values()
    keywords = {p.name for p in parameters if p.kind in {p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY}}
    assert typed_dict.__required_keys__ == frozenset()
    assert typed_dict.__optional_keys__ == keywords - {"self", *passed_separately}
