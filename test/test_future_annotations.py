"""Endpoints in a module with ``from __future__ import annotations``.

There, ``inspect.signature`` gives every annotation as a string, so ClientX has to
evaluate them to find the request-part helpers. The client is defined at module level
because annotations are evaluated against the module's globals.
"""

from __future__ import annotations

from typing import Annotated

import httpx2
from pydantic import BaseModel

from clientx import ClientX, Header, Query, Response
from clientx.methods import get, post
from clientx.tools import list_tools

type Page = Annotated[int | None, Query("p")]


class Filters(BaseModel):
    status: str
    trace: Annotated[str | None, Header("X-Trace")] = None


class FutureAPI(ClientX):
    @get("/items/{item_id}")
    def item(
        self,
        item_id: int,
        page: Page = None,
        request_id: Annotated[str | None, Header("X-Request-Id")] = None,
    ) -> Response: ...

    @post("/search")
    def search(self, filters: Filters) -> Response: ...


def _client(sent: list[httpx2.Request]) -> FutureAPI:
    return FutureAPI(
        "https://api.example.com", transport=httpx2.MockTransport(lambda r: sent.append(r) or httpx2.Response(200))
    )


def test_helpers_in_string_annotations_are_read():
    sent: list[httpx2.Request] = []

    _client(sent).item(7, page=2, request_id="abc")

    [request] = sent
    assert str(request.url) == "https://api.example.com/items/7?p=2"
    assert request.headers["X-Request-Id"] == "abc"


def test_models_in_string_annotations_are_expanded():
    sent: list[httpx2.Request] = []

    _client(sent).search(Filters(status="open", trace="t-1"))

    [request] = sent
    assert request.headers["X-Trace"] == "t-1"
    assert request.content == b'{"status":"open"}'


def test_tool_schemas_use_the_evaluated_annotations():
    tools = {tool.name: tool for tool in list_tools(_client([]))}

    properties = tools["item"].input_schema["properties"]
    assert properties["item_id"]["type"] == "integer"
    assert properties["request_id"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
