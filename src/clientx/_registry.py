"""Map endpoint functions to their ``Endpoint``, and tool methods to theirs.

The verb decorators register each endpoint function here, and ``@tool`` each
method it makes a tool, so ``_class_setup.py`` can find a client's or
resource's endpoints and tools when the class is defined, to check them and
apply a resource's prefix and tags, and ``list_tools`` can find them on a
client. ``Endpoint`` and ``ToolMethod`` are imported only for type checking:
nothing here uses them at runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from clientx._endpoint import Endpoint
    from clientx._tools import ToolMethod

# Keyed by id() so lookups never hash arbitrary class attributes. Each entry
# keeps its function alive, so the id can't be reused by another object.
_endpoints: dict[int, tuple[Callable[..., Any], Endpoint]] = {}
_tool_methods: dict[int, tuple[Callable[..., Any], ToolMethod]] = {}


def register_endpoint_function(func: Callable[..., Any], endpoint: Endpoint) -> None:
    """Record that the decorator returned ``func`` for ``endpoint``."""
    _endpoints[id(func)] = (func, endpoint)


def endpoint_for(value: object) -> Endpoint | None:
    """Return the ``Endpoint`` of an endpoint function, or ``None``."""
    entry = _endpoints.get(id(value))
    if entry is not None and entry[0] is value:
        return entry[1]
    return None


def register_tool_method(func: Callable[..., Any], tool_method: ToolMethod) -> None:
    """Record that ``@tool`` made ``func`` a tool."""
    _tool_methods[id(func)] = (func, tool_method)


def tool_method_for(value: object) -> ToolMethod | None:
    """Return the ``ToolMethod`` of a method ``@tool`` marked, or ``None``."""
    entry = _tool_methods.get(id(value))
    if entry is not None and entry[0] is value:
        return entry[1]
    return None
