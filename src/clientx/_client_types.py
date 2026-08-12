import ssl
from collections.abc import Callable, Mapping
from http.cookiejar import CookieJar
from typing import Any, Literal, TypedDict

import httpx2

type Decoder = Callable[[httpx2.Response], object]

type DeprecatedType = Callable[..., None]

type MethodType = Literal["GET", "PUT", "POST", "PATCH", "DELETE", "HEAD", "OPTIONS"]

type CookieTypes = httpx2.Cookies | CookieJar | dict[str, str] | list[tuple[str, str]]

type EventHook = Callable[[httpx2.Request | httpx2.Response], None]

type EventHooks = Mapping[str, list[EventHook]]

type RequestPartName = Literal[
    "params",
    "files",
    "data",
    "json",
    "headers",
]


def is_none_type(return_type: Any) -> bool:
    return return_type is type(None)


def is_response_type(return_type: Any) -> bool:
    return return_type is httpx2.Response


class HttpxClientKwargs(TypedDict, total=False):
    """Keyword arguments supported by httpx2.Client.

    Intended for use with **kwargs: Unpack[HttpxClientKwargs] to preserve
    IDE autocomplete and static type checking.
    """

    auth: httpx2.Auth | tuple[str, str] | tuple[bytes, bytes] | None
    """An authentication class or tuple to use when sending requests."""

    params: httpx2.QueryParams | None
    """Query parameters to include in request URLs."""

    headers: Mapping[str, str] | None
    """HTTP headers to include when sending requests."""

    cookies: CookieTypes | None
    """Cookie items to include when sending requests."""

    verify: bool | str | ssl.SSLContext
    """TLS verification configuration (True, False, or SSLContext)."""

    http2: bool
    """Enable or disable HTTP/2 support."""

    proxy: str | httpx2.URL | httpx2.Proxy | None
    """A proxy URL or configuration where all traffic should be routed."""

    timeout: httpx2.Timeout | float | None
    """Timeout configuration to use when sending requests."""

    limits: httpx2.Limits
    """Connection pool limits configuration."""

    max_redirects: int
    """Maximum number of redirect responses to follow."""

    transport: httpx2.BaseTransport
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
    - "request": Called with an ``httpx2.Request`` object immediately before
        the request is sent.
    - "response": Called with an ``httpx2.Response`` object as soon as the
        response headers are received.

    Each hook value must be a list of callables. Hook callables are invoked in
    the order they appear in the list.

    Note:
        Response hooks are triggered before the response body is fully read.
        Hooks should avoid consuming the response body or performing blocking
        operations that depend on the full response content.
    """
