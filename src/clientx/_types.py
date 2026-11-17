# Required: the httpx2 aliases below are imported only under TYPE_CHECKING.
from __future__ import annotations

import ssl
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, TypedDict

from httpx2 import AsyncBaseTransport, BaseTransport, Limits, Request, Response

# httpx2 exports the `USE_CLIENT_DEFAULT` value but not its class, so this is the one place that imports
# the class from httpx2's private module. Other modules import it from here, so a move upstream is a
# one-line fix.
from httpx2._client import UseClientDefault

# _types is private: import for type checking only, so an httpx2
# refactor can break type checks but never runtime imports.
from httpx2._types import (
    AuthTypes,
    CertTypes,
    CookieTypes,
    HeaderTypes,
    ProxyTypes,
    QueryParamTypes,
    RequestContent,
    RequestData,
    RequestExtensions,
    RequestFiles,
    TimeoutTypes,
)


class HttpxArgument(StrEnum):
    """A part of an HTTP request, named after the ``httpx2.Client.build_request`` argument that sets it."""

    URL = "url"
    PARAMS = "params"
    HEADERS = "headers"
    COOKIES = "cookies"
    CONTENT = "content"
    DATA = "data"
    FILES = "files"
    JSON = "json"


@dataclass(frozen=True)
class HttpxArgumentSpec:
    """Field metadata that says which part of the request an endpoint parameter goes to.

    The helpers in ``clientx.arguments`` add it to ``FieldInfo.metadata``, and ``get_argument_spec`` in
    ``_arguments.py`` reads it.

    Attributes:
        in_: The request part. Named like OpenAPI's ``in``, with an underscore because ``in`` is a keyword.
    """

    in_: HttpxArgument


type MethodType = Literal["GET", "PUT", "POST", "PATCH", "DELETE", "HEAD", "OPTIONS"]

type Decoder = Callable[[Response], object]

type EventHook = Callable[[Request], object] | Callable[[Response], object]
"""A sync hook: called with the request (``"request"``) or response (``"response"``)."""

type AsyncEventHook = Callable[[Request], Awaitable[object]] | Callable[[Response], Awaitable[object]]
"""An async hook: like ``EventHook`` but must be an ``async def``."""


class _HttpxClientOptions(TypedDict, total=False):
    """The keyword arguments ``Client`` and ``AsyncClient`` share.

    They differ in ``transport``, ``mounts`` and ``event_hooks``, which take sync
    or async objects, so those live in ``HttpxClientOptions`` and
    ``AsyncHttpxClientOptions``.

    Every constructor parameter except ``base_url`` is included, deprecated ones
    too, so subclasses of ``Client`` / ``AsyncClient`` can forward ``**options``
    unchanged. ``ClientX`` takes ``base_url`` as a parameter of its own.
    """

    auth: AuthTypes | None
    """Authentication: an ``Auth``, a (username, password) tuple, or a callable that signs each request."""

    params: QueryParamTypes | None
    """Query parameters to include in request URLs: a mapping, a list of pairs, a string, or ``QueryParams``."""

    headers: HeaderTypes | None
    """HTTP headers to include when sending requests: a mapping, a list of pairs, or ``Headers``."""

    cookies: CookieTypes | None
    """Cookie items to include when sending requests."""

    verify: bool | str | ssl.SSLContext
    """TLS verification: ``True`` (system trust store), ``False`` (disabled), or an ``ssl.SSLContext``.

    Deprecated: a CA-bundle path ``str`` still works but emits a
    ``DeprecationWarning``; build an ``ssl.SSLContext`` instead.
    """

    cert: CertTypes | None
    """Client certificate for TLS: a cert file, (cert, key), or (cert, key, password).

    Deprecated: emits a ``DeprecationWarning``. Build an ``ssl.SSLContext``, call
    ``.load_cert_chain()``, and pass it as ``verify``.
    """

    http1: bool
    """Enable or disable HTTP/1.1 support."""

    http2: bool
    """Enable or disable HTTP/2 support."""

    proxy: ProxyTypes | None
    """A proxy URL or configuration where all traffic should be routed."""

    timeout: TimeoutTypes
    """Timeouts: seconds, ``None`` for none, a (connect, read, write, pool) tuple, or an ``Timeout``."""

    follow_redirects: bool
    """Whether to follow HTTP redirect responses."""

    limits: Limits
    """Connection pool limits configuration."""

    max_redirects: int
    """Maximum number of redirect responses to follow."""

    trust_env: bool
    """Enable or disable usage of environment variables for configuration."""

    default_encoding: str | Callable[[bytes], str | None]
    """Default encoding for decoding response text when no charset is present."""


class HttpxClientOptions(_HttpxClientOptions, total=False):
    """Keyword arguments of ``Client.__init__``.

    Use as ``**options: Unpack[HttpxClientOptions]`` in a subclass ``__init__``.
    """

    mounts: Mapping[str, BaseTransport | None] | None
    """Transports to use for requests matching URL patterns, keyed by pattern."""

    transport: BaseTransport | None
    """Transport instance used to send requests over the network."""

    event_hooks: Mapping[str, list[EventHook]] | None
    """Optional event hooks to invoke during request and response processing.

    Supported hook types:
    - "request": called with an ``Request`` immediately before it is sent.
    - "response": called with an ``Response`` as soon as the response
      headers are received.

    Each value is a list of callables, invoked in list order.

    Note:
        Response hooks run before the body is read. Avoid consuming the body or
        doing blocking work that depends on the full content.
    """


class AsyncHttpxClientOptions(_HttpxClientOptions, total=False):
    """Keyword arguments of ``AsyncClient.__init__``.

    The same as ``HttpxClientOptions``, except ``mounts`` and ``transport`` take
    async transports and event hooks must be ``async`` functions.
    """

    mounts: Mapping[str, AsyncBaseTransport | None] | None
    """Transports to use for requests matching URL patterns, keyed by pattern."""

    transport: AsyncBaseTransport | None
    """Transport instance used to send requests over the network."""

    event_hooks: Mapping[str, list[AsyncEventHook]] | None
    """Optional async event hooks to invoke during request and response processing.

    Supported hook types:
    - "request": called with an ``Request`` immediately before it is sent.
    - "response": called with an ``Response`` as soon as the response
      headers are received.

    Each value is a list of ``async`` callables, invoked in list order.

    Note:
        Response hooks run before the body is read. Avoid consuming the body or
        doing blocking work that depends on the full content.
    """


class BuildRequestKwargs(TypedDict, total=False):
    """Keyword arguments of ``Client.build_request`` and ``AsyncClient.build_request``, after ``method`` and ``url``.

    ``RequestPlan.build`` fills the parts that carry an endpoint's arguments, and
    ``Endpoint.request_arguments`` adds ``timeout``. ClientX never sets ``cookies`` or
    ``extensions``: they're listed so the keys match ``build_request``'s parameters.
    """

    content: RequestContent | None
    """The raw body: ``str``, ``bytes``, or an iterable of ``bytes``. A ``Body()`` parameter sets it."""

    data: RequestData | None
    """Form fields, form-encoded, or a multipart form with ``files``. ``Form()`` parameters set it."""

    files: RequestFiles | None
    """Files to upload in a multipart form. ``File()`` parameters set it."""

    json: Any | None
    """A JSON body. ``Json()`` parameters, and models, mappings and collections without a helper, set it."""

    params: QueryParamTypes | None
    """Query parameters, merged with the client's. ``Query()`` parameters, and plain values without a helper, set it."""

    headers: HeaderTypes | None
    """HTTP headers, merged with the client's. ``Header()`` parameters set it."""

    cookies: CookieTypes | None
    """Cookies, merged with the client's. ClientX never sets it: there's no ``Cookie()`` helper."""

    timeout: TimeoutTypes | UseClientDefault
    """The request's timeout, or ``USE_CLIENT_DEFAULT`` for the client's. The endpoint's ``timeout=`` sets it."""

    extensions: RequestExtensions | None
    """Options for the transport, such as a ``trace`` callback. ClientX never sets it."""
