"""Map endpoint functions to their ``Endpoint`` objects.

The verb decorators register each endpoint function here, so ``ClientX`` and
``Resource`` can find their endpoints when a subclass is defined (to check names
and apply a resource's prefix and tags). This module imports nothing else from
ClientX at runtime, so ``_client.py`` can use it without a circular import.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from clientx._endpoint_context import Endpoint

# Keyed by id() so lookups never hash arbitrary class attributes. Ids can't be
# reused: each Endpoint keeps its function alive through `Endpoint.func`.
_endpoints: dict[int, Endpoint] = {}


def register_endpoint_function(func: Callable[..., Any], endpoint: Endpoint) -> None:
    """Record that ``func`` is the function the decorator returned for ``endpoint``."""
    _endpoints[id(func)] = endpoint


def endpoint_for(value: object) -> Endpoint | None:
    """Return the ``Endpoint`` for an endpoint function, or ``None`` for anything else."""
    endpoint = _endpoints.get(id(value))
    if endpoint is not None and endpoint.func is value:
        return endpoint
    return None
