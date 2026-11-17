"""The machinery behind the experimental ``clientx.arguments`` helpers.

``clientx.arguments`` builds its helpers with ``bind_argument`` and re-exports ``HttpxArgument`` and
``get_argument_location``. ``HttpxArgumentLocation``, the mark a helper adds to a field, stays here, so how a
field is marked can change without breaking users.
"""

import functools
from collections.abc import Callable
from typing import Any, ParamSpec

from pydantic.fields import FieldInfo

from clientx._types import HttpxArgument, HttpxArgumentSpec

P = ParamSpec("P")


def get_argument_location(field_info: object) -> HttpxArgument | None:
    """The request argument a field is marked for, or ``None`` if it's not a ``FieldInfo`` or has no mark."""
    if not isinstance(field_info, FieldInfo):
        return None
    return next((meta.in_ for meta in field_info.metadata if isinstance(meta, HttpxArgumentSpec)), None)


def bind_argument(
    name: str,
    location: HttpxArgument,
    field_fn: Callable[P, Any],
) -> Callable[P, Any]:
    """Wrap a ``Field``-like function so each field it creates is marked for ``location``.

    The wrapper takes the same arguments as ``field_fn`` (through ``ParamSpec``), so editors offer
    ``pydantic.Field``'s parameters for each helper. At runtime it has its own name and docstring, and
    ``functools.wraps`` records ``field_fn`` as the wrapped function, so ``help()`` and
    ``inspect.signature()`` show ``field_fn``'s arguments rather than ``*args, **kwargs``.

    Args:
        name: The helper's name, for its ``__name__`` and ``__qualname__``.
        location: The request part to mark each field for.
        field_fn: The function that creates the ``FieldInfo``, normally ``pydantic.Field``.

    Returns:
        A function that calls ``field_fn`` with its arguments and adds an ``HttpxArgumentLocation`` for
        ``location`` to the returned field's metadata.
    """

    @functools.wraps(field_fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        field_info = field_fn(*args, **kwargs)
        field_info.metadata.append(HttpxArgumentSpec(in_=location))
        return field_info

    wrapper.__name__ = wrapper.__qualname__ = name
    # The public module that exports the helpers, so help() and reprs show the path users import from.
    # functools.wraps copied field_fn's module, such as pydantic.fields.
    wrapper.__module__ = "clientx.arguments"
    wrapper.__doc__ = (
        f"Create a ``pydantic.Field`` for an endpoint parameter that goes to the request's ``{location}``.\n\n"
        "Takes the same arguments as ``pydantic.Field``; see ``help(pydantic.Field)``."
    )
    return wrapper
