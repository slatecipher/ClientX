import ssl
from collections.abc import Callable, Mapping, Sequence
from http.cookiejar import CookieJar
from typing import Any, Literal, TypedDict

import httpx2

type Decoder = Callable[[httpx2.Response], object]

type DeprecatedType = Callable[..., None]

type MethodType = Literal["GET", "PUT", "POST", "PATCH", "DELETE", "HEAD", "OPTIONS"]

# The option types below mirror httpx2's private aliases (httpx2._types), so each `ClientX(...)` option
# accepts what `httpx2.Client` does. test/test_typing.py passes every form to catch a narrower copy.
type PrimitiveData = str | int | float | bool | None

type QueryParamTypes = (
    httpx2.QueryParams
    | Mapping[str, PrimitiveData | Sequence[PrimitiveData]]
    | list[tuple[str, PrimitiveData]]
    | tuple[tuple[str, PrimitiveData], ...]
    | str
    | bytes
)

type HeaderTypes = (
    httpx2.Headers
    | Mapping[str, str]
    | Mapping[bytes, bytes]
    | Sequence[tuple[str, str]]
    | Sequence[tuple[bytes, bytes]]
)

type AuthTypes = tuple[str | bytes, str | bytes] | Callable[[httpx2.Request], httpx2.Request] | httpx2.Auth

type TimeoutTypes = float | None | tuple[float | None, float | None, float | None, float | None] | httpx2.Timeout

type ProxyTypes = httpx2.URL | str | httpx2.Proxy

type CookieTypes = httpx2.Cookies | CookieJar | dict[str, str] | list[tuple[str, str]]

# Mirrors httpx2's private CertTypes: a cert file, (cert, key), or (cert, key, password).
type CertTypes = str | tuple[str, str] | tuple[str, str, str]

# Mirrors httpx2's EventHook (Callable[..., Any]). Request hooks receive an
# httpx2.Request and response hooks an httpx2.Response, so one precise callable
# type can't describe both. Callable[[Request | Response], None] would reject a
# hook typed for the one object it receives.
type EventHook = Callable[..., object]

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


# Parameter descriptions adapted from the httpx2.Client docstring.
# httpx2: BSD-3-Clause, Copyright © 2019 Encode OSS Ltd; © 2026 Pydantic Services Inc. and contributors.
class _HttpxClientOptions(TypedDict, total=False):
    """The keyword arguments ``httpx2.Client`` and ``httpx2.AsyncClient`` share.

    They differ only in ``transport`` and ``mounts``, which take sync or async
    transports, so those are in ``HttpxClientKwargs`` and ``AsyncHttpxClientKwargs``.
    """

    auth: AuthTypes | None
    """Authentication: an ``httpx2.Auth``, a (username, password) tuple, or a callable that signs each request."""

    params: QueryParamTypes | None
    """Query parameters to include in request URLs: a mapping, a list of pairs, a string, or ``QueryParams``."""

    headers: HeaderTypes | None
    """HTTP headers to include when sending requests: a mapping, a list of pairs, or ``Headers``."""

    cookies: CookieTypes | None
    """Cookie items to include when sending requests."""

    verify: bool | str | ssl.SSLContext
    """TLS verification configuration (True, False, or SSLContext)."""

    cert: CertTypes | None
    """Client certificate for TLS: a cert file, (cert, key), or (cert, key, password)."""

    http1: bool
    """Enable or disable HTTP/1.1 support."""

    http2: bool
    """Enable or disable HTTP/2 support."""

    proxy: ProxyTypes | None
    """A proxy URL or configuration where all traffic should be routed."""

    timeout: TimeoutTypes
    """Timeouts: seconds, ``None`` for none, a (connect, read, write, pool) tuple, or an ``httpx2.Timeout``."""

    follow_redirects: bool
    """Whether to follow HTTP redirect responses."""

    limits: httpx2.Limits
    """Connection pool limits configuration."""

    max_redirects: int
    """Maximum number of redirect responses to follow."""

    trust_env: bool
    """Enable or disable usage of environment variables for configuration."""

    default_encoding: str | Callable[[bytes], str | None]
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


class HttpxClientKwargs(_HttpxClientOptions, total=False):
    """Keyword arguments supported by ``httpx2.Client``.

    Intended for use with ``**kwargs: Unpack[HttpxClientKwargs]`` to preserve
    IDE autocomplete and static type checking.
    """

    mounts: Mapping[str, httpx2.BaseTransport | None] | None
    """Transports to use for requests matching URL patterns, keyed by pattern."""

    transport: httpx2.BaseTransport | None
    """Transport instance used to send requests over the network."""


class AsyncHttpxClientKwargs(_HttpxClientOptions, total=False):
    """Keyword arguments supported by ``httpx2.AsyncClient``.

    The same as ``HttpxClientKwargs``, except that ``mounts`` and ``transport`` take
    async transports, and event hooks must be ``async`` functions.
    """

    mounts: Mapping[str, httpx2.AsyncBaseTransport | None] | None
    """Transports to use for requests matching URL patterns, keyed by pattern."""

    transport: httpx2.AsyncBaseTransport | None
    """Transport instance used to send requests over the network."""


class DumpConfig(TypedDict, total=False):
    """The ``pydantic.BaseModel.model_dump`` options ClientX supports.

    This is a chosen subset of ``model_dump``'s keyword arguments, not a full copy:
    a Pydantic option is added here only when building a request needs it, and every
    key exists in the lowest Pydantic version ClientX supports. Because
    ``total=False``, all keys are optional. ClientX dumps with ``mode="json"`` and
    ``by_alias=True``; any other option that is left out uses Pydantic's default.

    Attributes:
        mode: Serialization mode. ``"json"`` (ClientX's default) gives JSON-compatible
            output; ``"python"`` keeps non-JSON Python objects.
        include: Include selector using Pydantic's include/exclude specification.
        exclude: Exclude selector using Pydantic's include/exclude specification.
        context: Extra context passed into Pydantic serializers. Defaults to ``None`` when not provided.
        by_alias: Uses field aliases as output keys when ``True`` (ClientX's default).
        exclude_unset: Excludes fields that were not explicitly set when ``True``.
        exclude_defaults: Excludes fields with default values when ``True``.
        exclude_none: Excludes fields with ``None`` values when ``True``.
        exclude_computed_fields: Excludes computed fields when ``True``.
        round_trip: Emits values suitable for round-tripping non-idempotent types when ``True``.
        warnings: Serialization error behavior. ``False``/``"none"`` ignores errors,
            ``True``/``"warn"`` emits warnings, and ``"error"`` raises.
        serialize_as_any: Enables duck-typing serialization behavior when ``True``.
    """

    mode: Literal["json", "python"] | str
    include: Any
    exclude: Any
    context: dict[str, Any] | None
    by_alias: bool | None
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool
    exclude_computed_fields: bool
    round_trip: bool
    warnings: bool | Literal["none", "warn", "error"]
    serialize_as_any: bool
