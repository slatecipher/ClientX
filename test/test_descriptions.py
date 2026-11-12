"""Parameter descriptions for AI tools, from the helpers' ``description=`` and from ``PathParam`` (#45)."""

import re
from typing import Annotated, Any

import httpx2
import pytest
from pydantic import BaseModel, Field

from clientx import Body, ClientX, Header, PathParam, Query, Resource, Response
from clientx.exceptions import EndpointSignatureError, MisplacedHelperError
from clientx.methods import get, post
from clientx.tools import list_tools


class Filters(BaseModel):
    status: Annotated[str | None, Query(description="Only posts with this status")] = None


class PostsAPI(ClientX):
    @get("/users/{user_id}/posts")
    def list_posts(
        self,
        user_id: Annotated[int, PathParam(description="The author's ID")],
        page: Annotated[int | None, Query("p", description="Page number, from 1")] = None,
        request_id: Annotated[str | None, Header("X-Request-Id")] = None,
    ) -> Response: ...

    @post("/search")
    def search(self, filters: Annotated[Filters, Body(description="What to search for")]) -> Response: ...

    @get("/both")
    def both(
        self,
        first: Annotated[int, Query(description="from the helper"), Field(description="from Field")],
        second: Annotated[int, Field(description="from Field"), Query(description="from the helper")],
    ) -> Response: ...


def schemas() -> dict[str, dict[str, Any]]:
    return {tool.name: tool.input_schema for tool in list_tools(PostsAPI("https://api.example.com"))}


def test_helper_and_path_descriptions_are_in_the_tool_schema():
    properties = schemas()["list_posts"]["properties"]

    assert properties["user_id"]["description"] == "The author's ID"
    assert properties["page"]["description"] == "Page number, from 1"
    assert "description" not in properties["request_id"]


def test_a_description_sits_next_to_a_models_ref():
    schema = schemas()["search"]

    assert schema["properties"]["filters"] == {"$ref": "#/$defs/Filters", "description": "What to search for"}
    assert schema["$defs"]["Filters"]["properties"]["status"]["description"] == "Only posts with this status"


def test_pydantic_field_description_wins_in_either_order():
    properties = schemas()["both"]["properties"]

    assert properties["first"]["description"] == "from Field"
    assert properties["second"]["description"] == "from Field"


def test_descriptions_dont_change_the_request(mock_transport):
    sent: list[httpx2.Request] = []
    api = PostsAPI("https://api.example.com", transport=mock_transport(sent))

    api.list_posts(7, page=2)
    api.search(Filters(status="open"))

    first, second = sent
    assert str(first.url) == "https://api.example.com/users/7/posts?p=2"
    # Body() sends the whole model as JSON, so its field's Query() doesn't apply here.
    assert second.content == b'{"status":"open"}'


def test_path_without_a_placeholder_raises_when_the_class_is_defined():
    with pytest.raises(
        EndpointSignatureError, match=re.escape("marks 'user_id' with PathParam(), but its path '/users'")
    ):

        class API(ClientX):  # pyright: ignore[reportUnusedClass]
            @get("/users")
            def users(self, user_id: Annotated[int, PathParam(description="The user's ID")]) -> Response: ...


def test_path_can_name_a_placeholder_from_a_resource_prefix():
    class Issues(Resource, prefix="/repos/{owner}/issues"):
        @get("/{number}")
        def retrieve(
            self, owner: Annotated[str, PathParam(description="Repository owner")], number: Annotated[int, PathParam()]
        ) -> Response: ...

    class API(ClientX):
        issues = Issues()

    [tool] = list_tools(API("https://api.example.com"))
    assert tool.input_schema["properties"]["owner"]["description"] == "Repository owner"


def test_path_without_a_placeholder_raises_when_the_resource_is_defined():
    with pytest.raises(EndpointSignatureError, match=re.escape("'/items/{item_id}' has no {owner} placeholder")):

        class Items(Resource, prefix="/items"):  # pyright: ignore[reportUnusedClass]
            @get("/{item_id}")
            def retrieve(self, owner: Annotated[str, PathParam()], item_id: int) -> Response: ...


def test_path_with_another_helper_raises():
    with pytest.raises(MisplacedHelperError, match=re.escape("has more than one helper: PathParam(), Query()")):

        class API(ClientX):  # pyright: ignore[reportUnusedClass]
            @get("/users/{user_id}")
            def user(self, user_id: Annotated[int, PathParam(), Query()]) -> Response: ...


def test_path_on_a_model_field_raises():
    class Located(BaseModel):
        user_id: Annotated[int, PathParam()]

    with pytest.raises(
        MisplacedHelperError, match=re.escape("'Located.user_id' has PathParam(), which only applies to")
    ):

        class API(ClientX):  # pyright: ignore[reportUnusedClass]
            @post("/locate")
            def locate(self, body: Located) -> Response: ...


def test_a_description_is_in_a_models_own_json_schema():
    # Not only for tools: any JSON Schema Pydantic builds from the annotation includes it.
    assert Filters.model_json_schema()["properties"]["status"]["description"] == "Only posts with this status"
