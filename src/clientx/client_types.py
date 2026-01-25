import ssl
from http.cookiejar import CookieJar
from typing import Any, Callable, Literal, Mapping, TypedDict

import httpx

type Decoder = Callable[[httpx.Response], object]

type DeprecatedType = Callable[..., None]

type MethodType = Literal["GET", "PUT", "POST", "PATCH", "DELETE", "HEAD", "OPTIONS"]

type CookieTypes = httpx.Cookies | CookieJar | dict[str, str] | list[tuple[str, str]]

type EventHook = Callable[[httpx.Request | httpx.Response], None]

type EventHooks = Mapping[str, list[EventHook]]


def is_none_type(return_type: Any) -> bool:
    return return_type is type(None)


def is_response_type(return_type: Any) -> bool:
    return return_type is httpx.Response


class HttpxClientKwargs(TypedDict, total=False):
    """Keyword arguments supported by httpx.Client.

    Intended for use with **kwargs: Unpack[HttpxClientKwargs] to preserve
    IDE autocomplete and static type checking.
    """

    auth: httpx.Auth | tuple[str, str] | tuple[bytes, bytes] | None
    """An authentication class or tuple to use when sending requests."""

    params: httpx.QueryParams | None
    """Query parameters to include in request URLs."""

    headers: Mapping[str, str] | None
    """HTTP headers to include when sending requests."""

    cookies: CookieTypes | None
    """Cookie items to include when sending requests."""

    verify: bool | str | ssl.SSLContext
    """TLS verification configuration (True, False, or SSLContext)."""

    http2: bool
    """Enable or disable HTTP/2 support."""

    proxy: str | httpx.URL | httpx.Proxy | None
    """A proxy URL or configuration where all traffic should be routed."""

    timeout: httpx.Timeout | float | None
    """Timeout configuration to use when sending requests."""

    limits: httpx.Limits
    """Connection pool limits configuration."""

    max_redirects: int
    """Maximum number of redirect responses to follow."""

    transport: httpx.BaseTransport
    """Transport instance used to send requests over the network."""

    trust_env: bool
    """Enable or disable usage of environment variables for configuration."""

    default_encoding: str | Callable[[bytes], str]
    """Default encoding for decoding response text when no charset is present."""

    event_hooks: EventHooks | None
    """Optional event hooks to invoke during request and response processing.

    Event hooks allow registering callables that will be invoked at specific
    points in the request lifecycle.

    Supported hook types:
    - "request": Called with an ``httpx.Request`` object immediately before
        the request is sent.
    - "response": Called with an ``httpx.Response`` object as soon as the
        response headers are received.

    Each hook value must be a list of callables. Hook callables are invoked in
    the order they appear in the list.

    Note:
        Response hooks are triggered before the response body is fully read.
        Hooks should avoid consuming the response body or performing blocking
        operations that depend on the full response content.
    """


__all__ = ["HttpxClientKwargs", "MethodType", "Decoder"]
