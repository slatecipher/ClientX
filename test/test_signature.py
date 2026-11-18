"""inspect_signature and ParameterInfo: what ClientX reads from a signature.

These test an internal module directly, because what they check (resolved
annotations, aliases expanded, which helper counts) is easier to see here than
through a request.
"""

import functools
from types import NoneType
from typing import Annotated, Any

import pytest
from pydantic import Field

from clientx import Header, Query, Send
from clientx._signature import NO_VALUE, ParameterInfo, ParameterKind, inspect_signature
from clientx._types import HttpxArgument

type UserId = Annotated[int, Field(gt=0)]
type QueryUserId = Annotated[UserId, Query()]
type QueryParam[T] = Annotated[T, Query()]
type NotGeneric[T] = int
type Embed = Annotated[int, Send(embed=True)]
# Deliberately cyclic, to check that alias expansion stops.
type Loop = Loop2  # pyright: ignore[reportGeneralTypeIssues]
type Loop2 = Loop


def parameter(annotation: Any) -> ParameterInfo:
    return ParameterInfo("p", 0, ParameterKind.POSITIONAL_OR_KEYWORD, annotation=annotation)


# ParameterInfo


@pytest.mark.parametrize(
    ("annotation", "part"),
    [
        pytest.param(Annotated[int, Query()], HttpxArgument.PARAMS, id="one helper"),
        pytest.param(Annotated[int, Field(gt=0), Query()], HttpxArgument.PARAMS, id="after a plain Field"),
        pytest.param(Annotated[int, Query(), Field(gt=0)], HttpxArgument.PARAMS, id="before a plain Field"),
        pytest.param(Annotated[int, Query(), Header()], HttpxArgument.HEADERS, id="the last of two"),
        pytest.param(Annotated[QueryUserId, Header()], HttpxArgument.HEADERS, id="the parameter's over an alias's"),
        pytest.param(QueryUserId, HttpxArgument.PARAMS, id="from an alias"),
        pytest.param(Annotated[int, Field(gt=0)], None, id="a plain Field isn't one"),
        # Python supports `|` on Annotated; pyright doesn't model it outside an
        # annotation.
        pytest.param(Annotated[int, Query()] | None, None, id="nested in a union isn't found"),  # pyright: ignore[reportOperatorIssue]
        pytest.param(int, None, id="no Annotated"),
    ],
)
def test_the_last_helper_in_the_outermost_annotated_counts(annotation: Any, part: HttpxArgument | None) -> None:
    info = parameter(annotation)
    assert info.httpx_argument is part
    assert (info.clientx_field_info is None) is (part is None)


@pytest.mark.parametrize(
    ("annotation", "send"),
    [
        pytest.param(Annotated[int, Send(embed=True)], Send(embed=True), id="one"),
        pytest.param(Annotated[int, Send(embed=True), Query()], Send(embed=True), id="before the helper"),
        pytest.param(Annotated[int, Send(embed=True), Send(embed=False)], Send(embed=False), id="the last of two"),
        pytest.param(Annotated[Embed, Send(embed=False)], Send(embed=False), id="the parameter's over an alias's"),
        pytest.param(Embed, Send(embed=True), id="from an alias"),
        pytest.param(Annotated[int, Query()], Send(), id="none"),
    ],
)
def test_the_last_send_in_the_outermost_annotated_counts(annotation: Any, send: Send) -> None:
    assert parameter(annotation).send == send


@pytest.mark.parametrize(
    ("annotation", "base_type"),
    [
        pytest.param(Annotated[int, Query()], int, id="Annotated"),
        pytest.param(UserId, int, id="type alias"),
        pytest.param(QueryUserId, int, id="alias of an alias"),
        pytest.param(QueryParam[str], str, id="generic alias"),
        pytest.param(NotGeneric[str], int, id="generic alias whose value takes no arguments"),
        pytest.param(int | None, int | None, id="union kept"),
        pytest.param(NO_VALUE, NO_VALUE, id="no annotation"),
    ],
)
def test_base_type_has_no_annotated_or_alias(annotation: Any, base_type: Any) -> None:
    assert parameter(annotation).base_type == base_type


def test_a_cyclic_alias_stops_instead_of_looping() -> None:
    parameter(Loop)  # Doesn't hang: alias expansion stops after a fixed depth.


# inspect_signature


def test_inspect_signature_describes_every_parameter() -> None:
    def endpoint(self: object, user_id: int, /, page: int = 1, *, verbose: bool = False) -> str:
        """Fetch a user."""
        return ""

    info = inspect_signature(endpoint)
    assert [(p.name, p.position, p.kind, p.default) for p in info.parameters] == [
        ("self", 0, ParameterKind.POSITIONAL_ONLY, NO_VALUE),
        ("user_id", 1, ParameterKind.POSITIONAL_ONLY, NO_VALUE),
        ("page", 2, ParameterKind.POSITIONAL_OR_KEYWORD, 1),
        ("verbose", 3, ParameterKind.KEYWORD_ONLY, False),
    ]
    assert (info.name, info.doc, info.is_async, info.returns.base_type) == ("endpoint", "Fetch a user.", False, str)
    assert info.qualname.endswith("<locals>.endpoint")
    assert info.module == __name__


def test_string_annotations_are_resolved_with_their_metadata() -> None:
    # As with `from __future__ import annotations`: names resolve in the
    # function's module.
    def endpoint(self: "object", user_id: "QueryUserId") -> "None": ...

    info = inspect_signature(endpoint)
    assert info.parameters[1].httpx_argument is HttpxArgument.PARAMS
    assert info.parameters[1].base_type is int
    assert info.returns.annotation is NoneType


def test_an_annotation_that_cant_be_resolved_raises() -> None:
    def endpoint(self: object, user: "UndefinedModel") -> None: ...  # noqa: F821  # pyright: ignore[reportUndefinedVariable]

    with pytest.raises(NameError, match="UndefinedModel"):
        inspect_signature(endpoint)


def test_a_wrapped_function_is_read_through_its_wrapper() -> None:
    async def endpoint(self: object, page: Annotated[int, Query()]) -> int:
        return page

    @functools.wraps(endpoint)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return endpoint(*args, **kwargs)

    info = inspect_signature(wrapper)
    assert info.is_async
    assert info.parameters[1].httpx_argument is HttpxArgument.PARAMS


def test_returns_keeps_the_annotations_metadata() -> None:
    def endpoint(self: object) -> UserId: ...

    returns = inspect_signature(endpoint).returns
    assert returns.base_type is int
    assert [type(item).__name__ for item in returns.metadata] == ["FieldInfo"]


def test_bind_fills_in_defaults() -> None:
    def endpoint(self: object, user_id: int, page: int = 1) -> None: ...

    assert inspect_signature(endpoint).bind("owner", 7) == {"self": "owner", "user_id": 7, "page": 1}
    with pytest.raises(TypeError):
        inspect_signature(endpoint).bind("owner")
