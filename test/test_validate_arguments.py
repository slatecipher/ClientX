"""Opt-in argument validation: arguments are checked against their annotations before sending (#2)."""

import enum
import io
from collections.abc import Callable
from typing import Annotated, BinaryIO

import httpx2
import pytest
from pydantic import BaseModel, Field

from clientx import ClientX, File, Query, Resource, Response
from clientx._registry import endpoint_for
from clientx.exceptions import ArgumentValidationError, ClientXError
from clientx.methods import get, post
from clientx.tools import list_tools


class Color(enum.StrEnum):
    RED = "red"


class Filters(BaseModel):
    status: str


class Items(Resource, prefix="/items"):
    @get("/{item_id}")
    def retrieve(self, item_id: int) -> Response: ...


class API(ClientX):
    items = Items()

    @get("/search")
    def search(
        self,
        page: Annotated[int, Query(), Field(ge=1)],
        ratio: Annotated[float | None, Query()] = None,
        color: Annotated[Color | None, Query()] = None,
    ) -> Response: ...

    @get("/legacy")
    def legacy(self, page: Annotated[int, Query()] = None) -> Response: ...  # pyright: ignore[reportArgumentType]

    @post("/filter")
    def filter(self, filters: Filters) -> Response: ...

    @post("/upload")
    def upload(self, files: Annotated[dict[str, BinaryIO], File()]) -> Response: ...

    @get("/always", validate_arguments=True)
    def always(self, page: Annotated[int, Query()]) -> Response: ...

    @get("/never", validate_arguments=False)
    def never(self, page: Annotated[int, Query()]) -> Response: ...


@pytest.fixture
def make_api(mock_transport) -> Callable[..., API]:
    def make(sent: list[httpx2.Request], *, validate_arguments: bool) -> API:
        return API("https://api.example.com", validate_arguments=validate_arguments, transport=mock_transport(sent))

    return make


def test_validation_is_off_by_default(mock_transport):
    sent: list[httpx2.Request] = []
    api = API("https://api.example.com", transport=mock_transport(sent))

    api.search("2")  # pyright: ignore[reportArgumentType]

    [request] = sent
    assert request.url.params["page"] == "2"


def test_an_argument_that_doesnt_match_raises_before_sending(make_api):
    sent: list[httpx2.Request] = []
    api = make_api(sent, validate_arguments=True)

    with pytest.raises(ArgumentValidationError) as info:
        api.search("2")  # pyright: ignore[reportArgumentType]

    assert sent == []
    assert info.value.parameter == "page"
    assert info.value.func is endpoint_for(API.search).func  # pyright: ignore[reportOptionalMemberAccess]
    assert "Argument 'page' of 'API.search' doesn't match its annotation" in str(info.value)
    assert info.value.__cause__ is info.value.validation_error
    assert isinstance(info.value, ClientXError)
    assert isinstance(info.value, ValueError)


def test_field_constraints_are_checked(make_api):
    api = make_api([], validate_arguments=True)

    with pytest.raises(ArgumentValidationError, match="greater than or equal to 1"):
        api.search(0)


def test_valid_arguments_are_sent_unchanged(make_api):
    sent: list[httpx2.Request] = []
    api = make_api(sent, validate_arguments=True)

    api.search(3, ratio=2, color=Color.RED)
    api.filter(Filters(status="open"))

    first, second = sent
    # Strict validation accepts an int for a float, and never converts the value: 2 is sent, not 2.0.
    assert first.url.params["page"] == "3"
    assert first.url.params["ratio"] == "2"
    assert first.url.params["color"] == "red"
    assert second.content == b'{"status":"open"}'


def test_a_value_isnt_converted_to_match(make_api):
    api = make_api([], validate_arguments=True)

    with pytest.raises(ArgumentValidationError, match="color"):
        api.search(1, color="red")  # pyright: ignore[reportArgumentType]


def test_defaults_arent_checked(make_api):
    sent: list[httpx2.Request] = []
    api = make_api(sent, validate_arguments=True)

    api.legacy()

    [request] = sent
    assert "page" not in request.url.params


def test_types_pydantic_cant_validate_are_skipped(make_api):
    sent: list[httpx2.Request] = []
    api = make_api(sent, validate_arguments=True)

    api.upload({"report": io.BytesIO(b"data")})

    assert len(sent) == 1


@pytest.mark.parametrize("client_setting", [True, False])
def test_an_endpoints_setting_wins_over_the_clients(client_setting: bool, make_api):
    sent: list[httpx2.Request] = []
    api = make_api(sent, validate_arguments=client_setting)

    with pytest.raises(ArgumentValidationError):
        api.always("1")  # pyright: ignore[reportArgumentType]
    api.never("1")  # pyright: ignore[reportArgumentType]

    assert [request.url.path for request in sent] == ["/never"]


def test_resource_endpoints_follow_the_root_clients_setting(make_api):
    sent: list[httpx2.Request] = []
    api = make_api(sent, validate_arguments=True)

    with pytest.raises(ArgumentValidationError, match="item_id"):
        api.items.retrieve("7")  # pyright: ignore[reportArgumentType]
    api.items.retrieve(7)

    assert [request.url.path for request in sent] == ["/items/7"]


def test_validators_are_built_once_per_parameter():
    class Cached(ClientX):
        @get("/search")
        def search(self, page: Annotated[int, Query()], ratio: Annotated[float | None, Query()] = None) -> Response: ...

    api = Cached(
        "https://api.example.com",
        validate_arguments=True,
        transport=httpx2.MockTransport(lambda r: httpx2.Response(200)),
    )
    endpoint = endpoint_for(Cached.search)
    assert endpoint is not None

    api.search(1)
    validators = dict(endpoint._validators)  # pyright: ignore[reportPrivateUsage]
    api.search(2, ratio=1.5)

    # Built on first use, only for arguments that were passed, then reused.
    assert set(validators) == {"page"}
    assert endpoint._validators["page"] is validators["page"]  # pyright: ignore[reportPrivateUsage]
    assert set(endpoint._validators) == {"page", "ratio"}  # pyright: ignore[reportPrivateUsage]


def test_tool_calls_pass_validation_after_converting_json_arguments(mock_transport):
    class Palette(ClientX):
        @get("/search")
        def search(self, color: Annotated[Color, Query()]) -> Response: ...

    sent: list[httpx2.Request] = []
    api = Palette(
        "https://api.example.com",
        validate_arguments=True,
        transport=mock_transport(sent),
    )
    [tool] = list_tools(api)

    # The tool's own validation turns the JSON string into a Color, so the strict check passes.
    tool.call({"color": "red"})

    [request] = sent
    assert request.url.params["color"] == "red"
