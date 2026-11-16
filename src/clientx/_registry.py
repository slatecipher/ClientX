"""Map endpoint functions to their ``Endpoint`` objects.

The verb decorators register each endpoint function here, so ``ClientX`` and
``Resource`` can find their endpoints when a subclass is defined (to check names
and apply a resource's prefix and tags), and so can ``clientx.tools`` and tests.
This module imports nothing else from ClientX at runtime: ``_endpoint.py``
imports ``_client.py``, so a runtime import here would be a cycle as soon as
``_client.py`` uses this module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from clientx._endpoint import Endpoint

# Keyed by id() so lookups never hash arbitrary class attributes. Each entry keeps
# its function alive, so the id can't be reused by another object.
_endpoints: dict[int, tuple[Callable[..., Any], Endpoint]] = {}


def register_endpoint_function(func: Callable[..., Any], endpoint: Endpoint) -> None:
    """Record that ``func`` is the function the decorator returned for ``endpoint``."""
    _endpoints[id(func)] = (func, endpoint)


def endpoint_for(value: object) -> Endpoint | None:
    """Return the ``Endpoint`` for an endpoint function, or ``None`` for anything else."""
    entry = _endpoints.get(id(value))
    if entry is not None and entry[0] is value:
        return entry[1]
    return None
