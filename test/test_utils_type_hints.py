import inspect
from typing import Annotated, Any, Literal, Optional, Union

import pytest

from clientx.utils.type_hints import NO_VALUE, describe_type, is_optional_type, is_union_type, unwrap_annotated


class Point:
    pass


def test_no_value_is_inspects_empty_sentinel():
    assert NO_VALUE is inspect.Parameter.empty
    assert NO_VALUE is inspect.Signature.empty


@pytest.mark.parametrize(
    ("type_hint", "expected"),
    [
        pytest.param(str, (str, ()), id="plain"),
        pytest.param(list[int], (list[int], ()), id="generic"),
        pytest.param(Annotated[int, "a", "b"], (int, ("a", "b")), id="annotated"),
        pytest.param(Annotated[Annotated[int, "a"], "b"], (int, ("a", "b")), id="nested-annotated-flattened"),
        pytest.param(Annotated[int | None, "a"], (int | None, ("a",)), id="annotated-optional"),
        # Annotated inside another type isn't the outer hint, so it stays where it is.
        pytest.param(
            Annotated[int, "a"] | None,  # pyright: ignore[reportOperatorIssue]
            (Annotated[int, "a"] | None, ()),  # pyright: ignore[reportOperatorIssue]
            id="annotated-inside-union",
        ),
        pytest.param(NO_VALUE, (NO_VALUE, ()), id="no-annotation"),
    ],
)
def test_unwrap_annotated(type_hint: Any, expected: tuple[Any, tuple[Any, ...]]):
    assert unwrap_annotated(type_hint) == expected


def test_unwrap_annotated_keeps_metadata_objects_themselves():
    marker = object()

    _, metadata = unwrap_annotated(Annotated[int, marker])

    assert metadata[0] is marker


@pytest.mark.parametrize(
    ("type_hint", "expected"),
    [
        pytest.param(int | str, True, id="pipe"),
        pytest.param(Union[int, str], True, id="typing-union"),  # noqa: UP007
        pytest.param(Optional[int], True, id="typing-optional"),  # noqa: UP045
        pytest.param(int, False, id="plain"),
        pytest.param(list[int | str], False, id="union-inside-generic"),
        pytest.param(Annotated[int | str, "a"], False, id="annotated-union"),
        pytest.param(NO_VALUE, False, id="no-annotation"),
    ],
)
def test_is_union_type(type_hint: Any, expected: bool):
    assert is_union_type(type_hint) is expected


@pytest.mark.parametrize(
    ("type_hint", "expected"),
    [
        pytest.param(int | None, True, id="pipe"),
        pytest.param(Optional[int], True, id="typing-optional"),  # noqa: UP045
        pytest.param(Union[int, None, str], True, id="typing-union-with-none"),  # noqa: UP007
        pytest.param(int | str, False, id="union-without-none"),
        pytest.param(int, False, id="plain"),
        pytest.param(type(None), False, id="none-alone"),
        pytest.param(list[int | None], False, id="optional-inside-generic"),
        # Callers pass the base type, with Annotated already removed (ParameterInfo.is_optional).
        pytest.param(Annotated[int | None, "a"], False, id="annotated-optional"),
    ],
)
def test_is_optional_type(type_hint: Any, expected: bool):
    assert is_optional_type(type_hint) is expected


@pytest.mark.parametrize(
    ("type_hint", "expected"),
    [
        pytest.param(NO_VALUE, "Any", id="no-annotation"),
        pytest.param(int, "int", id="builtin"),
        pytest.param(Point, "Point", id="class-name-only"),
        pytest.param(list[str], "list[str]", id="generic"),
        pytest.param(dict[str, int], "dict[str, int]", id="generic-two-args"),
        pytest.param(int | None, "int | None", id="pipe-optional"),
        pytest.param(Any, "Any", id="typing-any"),
        pytest.param(Literal["a", "b"], "Literal['a', 'b']", id="literal"),
        pytest.param("Point", "Point", id="unresolved-string"),
    ],
)
def test_describe_type(type_hint: Any, expected: str):
    assert describe_type(type_hint) == expected
