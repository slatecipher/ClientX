import warnings
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Concatenate, ParamSpec, TypeVar, cast

from httpx2 import USE_CLIENT_DEFAULT, Timeout

from clientx._client import AsyncClientX, ClientX, EndpointOwner, client_of
from clientx._decoding import adecode, araise_status_error, decode, raise_status_error
from clientx._endpoint import Endpoint
from clientx._registry import register_endpoint_function
from clientx._signature import inspect_signature
from clientx._types import Decoder, MethodType, UseClientDefault

P = ParamSpec("P")
T = TypeVar("T", bound=EndpointOwner)
R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class Method:
    method: MethodType

    def __call__(
        self,
        path: str = "",
        *,
        decoder: Decoder | None = None,
        stream: bool = False,
        deprecated: str | None = None,
        tags: list[str] | None = None,
        timeout: Timeout | float | None | UseClientDefault = USE_CLIENT_DEFAULT,
        raise_for_status: bool | None = None,
        validate_arguments: bool | None = None,
    ) -> Callable[[Callable[Concatenate[T, P], R]], Callable[Concatenate[T, P], R]]:
        def decorator(func: Callable[Concatenate[T, P], R]) -> Callable[Concatenate[T, P], R]:
            endpoint = Endpoint(
                method=self.method,
                raw_path=path,
                signature=inspect_signature(func),
                tags=tags,
                timeout=timeout,
                raise_for_status=raise_for_status,
                validate_arguments=validate_arguments,
                decoder=decoder,
                stream_response=stream,
                deprecated=deprecated,
            )

            @wraps(func)
            def wrapper(_self: T, /, *args: P.args, **kwargs: P.kwargs) -> R:
                if endpoint.deprecated is not None:
                    # `stacklevel=2` names the caller's line. The warning must stay in the wrapper's own frame.
                    warnings.warn(endpoint.deprecated, DeprecationWarning, stacklevel=2)
                client = client_of(_self, ClientX)
                arguments = endpoint.bind(_self, *args, **kwargs)
                url, request_arguments = endpoint.request_arguments(arguments)
                request = client.build_request(endpoint.method, url, **request_arguments)
                response = client.send(request, stream=endpoint.stream)
                if response.is_error and _raises_for_status(endpoint, client):
                    raise_status_error(response)
                if endpoint.stream_response:
                    return cast(R, response)  # Open and unread: the caller reads and closes it.
                return cast(R, decode(endpoint.decoder, response, stream=endpoint.stream))

            @wraps(func)
            async def async_wrapper(_self: T, /, *args: P.args, **kwargs: P.kwargs) -> object:
                if endpoint.deprecated is not None:
                    warnings.warn(endpoint.deprecated, DeprecationWarning, stacklevel=2)
                client = client_of(_self, AsyncClientX)
                arguments = endpoint.bind(_self, *args, **kwargs)
                url, request_arguments = endpoint.request_arguments(arguments)
                request = client.build_request(endpoint.method, url, **request_arguments)
                response = await client.send(request, stream=endpoint.stream)
                if response.is_error and _raises_for_status(endpoint, client):
                    await araise_status_error(response)
                if endpoint.stream_response:
                    return response  # Open and unread: the caller reads and closes it.
                return await adecode(endpoint.decoder, response, stream=endpoint.stream)

            endpoint_function = (
                cast(Callable[Concatenate[T, P], R], async_wrapper) if endpoint.signature.is_async else wrapper
            )
            register_endpoint_function(endpoint_function, endpoint)
            return endpoint_function

        return decorator


def _raises_for_status(endpoint: Endpoint, client: ClientX | AsyncClientX) -> bool:
    """Return whether ``endpoint`` raises for a 4xx or 5xx: its own setting if it has one, or else the client's.

    Not ``or``: an endpoint's ``False`` must win over the client's ``True``.
    """
    return client.__clientx_raise_for_status__ if endpoint.raise_for_status is None else endpoint.raise_for_status
