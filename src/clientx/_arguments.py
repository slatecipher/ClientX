"""The machinery behind the ``clientx.arguments`` helpers.

``clientx.arguments`` builds its helpers with ``bind_argument``.
``HttpxArgumentSpec``, the mark a helper adds to its ``FieldInfo``, isn't
public, so how a helper marks its ``FieldInfo`` can change without breaking
users. ``get_argument_spec`` and ``get_argument_location`` read the mark for the
rest of ClientX.
"""

import functools
from collections.abc import Callable
from typing import Any

from pydantic.fields import FieldInfo

from clientx._types import HttpxArgument, HttpxArgumentSpec


def get_argument_spec(field_info: object) -> HttpxArgumentSpec | None:
    """Return the helper's mark on ``field_info``, or ``None`` if there's none.

    A helper adds one mark. If there are several, the last one wins, as the last
    helper in an ``Annotated`` does.
    """
    if not isinstance(field_info, FieldInfo):
        return None
    return next((meta for meta in reversed(field_info.metadata) if isinstance(meta, HttpxArgumentSpec)), None)


def get_argument_location(field_info: object) -> HttpxArgument | None:
    """Return the request part ``field_info`` is marked for, or ``None``."""
    spec = get_argument_spec(field_info)
    return None if spec is None else spec.in_


def bind_argument[**P](
    name: str,
    location: HttpxArgument,
    field_fn: Callable[P, Any],
) -> Callable[P, Any]:
    """Wrap ``field_fn`` so each field it creates is marked for ``location``.

    The wrapper takes the same arguments as ``field_fn`` (through
    ``ParamSpec``), so editors offer ``pydantic.Field``'s parameters for each
    helper. At runtime it has its own name and docstring, and
    ``functools.wraps`` records ``field_fn`` as the wrapped function, so
    ``help()`` and ``inspect.signature()`` show ``field_fn``'s arguments rather
    than ``*args, **kwargs``.

    Args:
        name: The helper's name, for its ``__name__`` and ``__qualname__``.
        location: The request part to mark each field for.
        field_fn: The function that creates the ``FieldInfo``, normally
            ``pydantic.Field``.
    """

    @functools.wraps(field_fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        field_info = field_fn(*args, **kwargs)
        field_info.metadata.append(HttpxArgumentSpec(in_=location))
        return field_info

    wrapper.__name__ = wrapper.__qualname__ = name
    # The public module that exports the helpers, so help() and reprs show the
    # path users import from. functools.wraps copied field_fn's module, such as
    # pydantic.fields.
    wrapper.__module__ = "clientx.arguments"
    wrapper.__doc__ = (
        f"Create a ``pydantic.Field`` for an endpoint parameter that goes to the request's ``{location}``.\n\n"
        "Takes the same arguments as ``pydantic.Field``; see ``help(pydantic.Field)``."
    )
    return wrapper
