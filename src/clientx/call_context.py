from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from clientx.client import ClientX
from clientx.endpoint_context import EndpointContext


@dataclass
class CallContext:
    """Capture call metadata for an endpoint invocation."""

    endpoint: EndpointContext
    """Endpoint metadata and signature for the invoked operation."""
    client: ClientX
    """Client instance associated with the call (typically the bound self)."""
    bound: inspect.BoundArguments
    """Arguments bound to the endpoint signature, with defaults applied."""

    @property
    def method(self) -> str:
        return self.endpoint.method

    @property
    def path(self):
        return self.endpoint.path

    @property
    def function_parameters(self):
        return self.endpoint.signature.parameters

    @property
    def return_type(self) -> Any:
        return self.endpoint.return_type

    @classmethod
    def from_call(
        cls,
        *,
        endpoint: EndpointContext,
        client: ClientX,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> "CallContext":
        """Build a call context by binding arguments to an endpoint signature.

        Args:
            endpoint: The endpoint being invoked.
            args: Positional arguments passed to the call.
            kwargs: Keyword arguments passed to the call.

        Returns:
            CallContext: The populated call context.
        """
        bound = endpoint.signature.bind(client, *args, **kwargs)
        bound.apply_defaults()

        return cls(
            endpoint=endpoint,
            client=client,
            bound=bound,
        )
