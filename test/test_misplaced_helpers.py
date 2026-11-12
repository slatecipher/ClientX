"""A helper applies to the whole parameter or field: one helper, in the outermost ``Annotated``.

A helper nested inside another type (``Annotated[int, Query()] | None``) or a second helper
would be ignored, so ClientX raises ``MisplacedHelperError`` instead.
"""

import re
from collections.abc import Callable
from typing import Annotated

import httpx2
import pytest
from pydantic import BaseModel, Field

from clientx import Body, ClientX, Header, Query, Response
from clientx.exceptions import MisplacedHelperError
from clientx.methods import get, post

type QueryParam[T] = Annotated[T, Query()]
type UserId = Annotated[int | None, Query("userId")]
type MaybePage = Annotated[int, Query()] | None
type Json = dict[str, Json] | list[Json] | str | int | float | bool | None


class Filters(BaseModel):
    user_id: int


# Each case is an endpoint function whose `page` parameter is annotated the way a user would write it.
NESTED = "Query() nested inside another type"
TWO = "more than one helper: Query(), Header()"


def inside_none(self: ClientX, page: Annotated[int, Query()] | None = None) -> Response: ...
def alias_inside_none(self: ClientX, page: QueryParam[int] | None = None) -> Response: ...
def alias_whose_value_nests_it(self: ClientX, page: MaybePage = None) -> Response: ...
def model_inside_none(self: ClientX, page: Annotated[Filters, Query()] | None = None) -> Response: ...
def inside_a_list(self: ClientX, page: list[Annotated[str, Query()]]) -> Response: ...
def two_levels_deep(self: ClientX, page: list[Annotated[str, Query()]] | None = None) -> Response: ...
def a_part_per_member(
    self: ClientX, page: Annotated[str, Header()] | Annotated[dict[str, str], Body()]
) -> Response: ...
def two_helpers(self: ClientX, page: Annotated[int, Query(), Header()]) -> Response: ...
def alias_plus_another_helper(self: ClientX, page: Annotated[UserId, Header()] = None) -> Response: ...


MISPLACED: list[tuple[Callable[..., Response], str]] = [
    (inside_none, NESTED),
    (alias_inside_none, NESTED),
    (alias_whose_value_nests_it, NESTED),
    (model_inside_none, NESTED),
    (inside_a_list, NESTED),
    (two_levels_deep, NESTED),
    (a_part_per_member, "Header() nested inside another type"),
    (two_helpers, TWO),
    (alias_plus_another_helper, TWO),
]


@pytest.mark.parametrize(("endpoint", "problem"), MISPLACED, ids=[endpoint.__name__ for endpoint, _ in MISPLACED])
def test_a_misplaced_helper_raises_when_the_class_is_defined(endpoint: Callable[..., Response], problem: str):
    with pytest.raises(MisplacedHelperError) as raised:
        type("API", (ClientX,), {"search": get("/search")(endpoint)})

    assert raised.value.name == "page"
    assert f"'page' has {problem}" in str(raised.value)
    assert "Annotated[int | None, Query()]" in str(raised.value)


def none_inside(self: ClientX, page: Annotated[int | None, Query()] = None) -> Response: ...
def none_inside_an_alias(self: ClientX, page: QueryParam[int | None] = None) -> Response: ...
def alias_with_none_inside(self: ClientX, page: UserId = None) -> Response: ...
def alias_plus_plain_metadata(self: ClientX, page: Annotated[UserId, "documented"] = None) -> Response: ...
def other_metadata_in_a_union(self: ClientX, page: Annotated[int, Field(gt=0)] | None = None) -> Response: ...
def recursive_alias(self: ClientX, page: Annotated[Json, Body()] = None) -> Response: ...
def no_helper(self: ClientX, params: dict[str, str] | None = None) -> Response: ...


WELL_PLACED = [
    none_inside,
    none_inside_an_alias,
    alias_with_none_inside,
    alias_plus_plain_metadata,
    other_metadata_in_a_union,
    recursive_alias,
    no_helper,
]


@pytest.mark.parametrize("endpoint", WELL_PLACED, ids=[endpoint.__name__ for endpoint in WELL_PLACED])
def test_a_helper_around_the_whole_type_is_accepted(endpoint: Callable[..., Response]):
    api_class = type("API", (ClientX,), {"search": get("/search")(endpoint)})

    assert "search" in vars(api_class)


class KeyInside(BaseModel):
    api_key: Annotated[str | None, Header("X-Api-Key")] = None
    q: str


class KeyNested(BaseModel):
    api_key: Annotated[str, Header("X-Api-Key")] | None = None
    q: str


class TwoHelpers(BaseModel):
    api_key: Annotated[str, Query(), Header()]


@pytest.mark.parametrize(
    ("model", "problem"),
    [
        (KeyNested(api_key="secret", q="x"), "'KeyNested.api_key' has Header() nested inside another type"),
        (TwoHelpers(api_key="secret"), "'TwoHelpers.api_key' has more than one helper: Query(), Header()"),
    ],
    ids=["nested", "two helpers"],
)
def test_a_misplaced_helper_on_a_model_field_raises_before_sending(model: BaseModel, problem: str, mock_transport):
    sent: list[httpx2.Request] = []

    class API(ClientX):
        @post("/search")
        def search(self, body: BaseModel) -> Response: ...

    api = API("https://api.example.com", transport=mock_transport(sent))

    with pytest.raises(MisplacedHelperError, match=re.escape(problem)):
        api.search(model)

    assert sent == []


def test_a_model_field_with_the_helper_around_the_whole_type_is_sent(mock_transport):
    sent: list[httpx2.Request] = []

    class API(ClientX):
        @post("/search")
        def search(self, body: KeyInside) -> Response: ...

    api = API("https://api.example.com", transport=mock_transport(sent))
    api.search(KeyInside(api_key="secret", q="x"))

    [request] = sent
    assert request.headers["X-Api-Key"] == "secret"
    assert request.content == b'{"q":"x"}'


@pytest.mark.parametrize(
    ("model", "problem"),
    [
        (KeyNested, "'KeyNested.api_key' has Header() nested inside another type"),
        (TwoHelpers, "'TwoHelpers.api_key' has more than one helper: Query(), Header()"),
    ],
    ids=["nested", "two helpers"],
)
def test_a_misplaced_helper_in_a_parameters_model_raises_when_the_class_is_defined(
    model: type[BaseModel], problem: str
):
    with pytest.raises(MisplacedHelperError, match=re.escape(problem)):

        class API(ClientX):  # pyright: ignore[reportUnusedClass]
            @post("/search")
            def search(self, body: model) -> Response: ...  # pyright: ignore[reportInvalidTypeForm]


def test_a_model_that_isnt_complete_is_checked_when_it_is_sent(mock_transport):
    class Later(BaseModel):
        api_key: Annotated[str, Header()] | None = None
        child: "Undefined | None" = None  # noqa: F821  # pyright: ignore[reportUndefinedVariable]

    class API(ClientX):
        @post("/search")
        def search(self, body: Later) -> Response: ...

    class Undefined(BaseModel):
        pass

    Later.model_rebuild(_types_namespace={"Undefined": Undefined})
    api = API("https://api.example.com", transport=mock_transport())

    with pytest.raises(MisplacedHelperError, match=re.escape("'Later.api_key' has Header() nested")):
        api.search(Later())
