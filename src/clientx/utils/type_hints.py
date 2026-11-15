"""
Helpers for taking type hints apart.

Shared by models.py (for descriptive properties such as ParameterInfo.is_optional)
and inspector.py (for splitting Annotated hints while building results).
"""
from __future__ import annotations

import inspect
import types
from typing import Annotated, Any, Union, get_args, get_origin

# inspect uses this sentinel to mean "no annotation" or "no default value".
NO_VALUE = inspect.Parameter.empty


# --------------------------------------------------------------------------- #
# Type hint helpers
# --------------------------------------------------------------------------- #
def unwrap_annotated(type_hint: Any) -> tuple[Any, tuple[Any, ...]]:
    """
    Split an Annotated type hint into its underlying type and its metadata.

    Nested Annotated hints are flattened, so all metadata ends up in one tuple.
    A hint that isn't Annotated comes back unchanged with empty metadata.

        unwrap_annotated(Annotated[int, Range(1, 10), Doc("id")])
            -> (int, (Range(1, 10), Doc("id")))
        unwrap_annotated(str)
            -> (str, ())
    """
    collected_metadata: tuple[Any, ...] = ()
    while get_origin(type_hint) is Annotated:
        underlying_type, *metadata_items = get_args(type_hint)
        collected_metadata = (*collected_metadata, *metadata_items)
        type_hint = underlying_type
    return type_hint, collected_metadata


def is_union_type(type_hint: Any) -> bool:
    """Return True for both `Union[A, B]` and the newer `A | B` syntax."""
    return get_origin(type_hint) in (Union, types.UnionType)


def is_optional_type(type_hint: Any) -> bool:
    """Return True if the type hint is a union that includes None, e.g. `int | None`."""
    return is_union_type(type_hint) and type(None) in get_args(type_hint)


def describe_type(type_hint: Any) -> str:
    """Return a readable name for a type hint, e.g. 'int', 'list[str]', 'int | None'."""
    if type_hint is NO_VALUE:
        return "Any"
    if isinstance(type_hint, type) and get_origin(type_hint) is None:
        return type_hint.__name__
    return str(type_hint).replace("typing.", "")
