import ssl
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, TypedDict

from httpx2 import AsyncBaseTransport, BaseTransport, Limits, Request, Response

# httpx2 exports the `USE_CLIENT_DEFAULT` value but not its class, so this is
# the one place that imports the class from httpx2's private module. Other
# modules import it from here, so a move upstream is a one-line fix.
from httpx2._client import UseClientDefault

# httpx2's aliases are in its private `_types` module. Other modules import them
# from here, so a move upstream is a fix in one place.
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


# --- Request parts and Send ---------------------------------------------------
class HttpxArgument(StrEnum):
    """A part of an HTTP request.

    Each is named after the ``httpx2.Client.build_request`` argument that sets
    it.
    """

    URL = "url"
    PARAMS = "params"
    HEADERS = "headers"
    COOKIES = "cookies"
    CONTENT = "content"
    DATA = "data"
    FILES = "files"
    JSON = "json"


@dataclass(frozen=True, slots=True, kw_only=True)
class Send:
    """Options that change how a parameter is sent.

    The helper says where a value goes; ``Send`` says how. Put it in the
    parameter's outermost ``Annotated``, next to the helper, as in
    ``Annotated[list[str], Json(), Send(embed=True)]``.

    Each option applies to some parts of the request only, and one where it
    can't apply raises ``DefinitionError`` when the class is defined, as does a
    ``Send`` on a path parameter, nested inside the type, or on a model's field.

    With several ``Send`` in one ``Annotated``, the last one wins whole, as the
    last helper does, so one on the parameter replaces one from a ``type``
    alias rather than adding to it.

    Attributes:
        embed: Send a lone ``Json()`` parameter under its alias or name, as a
            field of a JSON object, instead of as the whole body:
            ``ids: Annotated[list[str], Json(), Send(embed=True)]`` sends
            ``{"ids": [...]}`` rather than ``[...]``. Like FastAPI's
            ``Body(embed=True)``. A parameter that's already keyed, a plain
            value or one of several ``Json()`` parameters, is sent the same.
        exclude_unset: Leave out what the caller didn't set, so the server's
            defaults apply: the parameter itself, when the caller didn't pass
            it, and a model's fields that weren't set when it was made (a
            pydantic model's only: a dataclass doesn't record them). For JSON,
            the query string, headers and form.
        exclude_none: Leave out the fields of a pydantic model or pydantic
            dataclass that are ``None``. For JSON only: the query string,
            headers and form leave out ``None`` already.
        exclude_defaults: Leave out the fields of a pydantic model or pydantic
            dataclass that equal their defaults. For JSON, and for a model
            spread into the query string, headers or form.
    """

    embed: bool | None = None
    exclude_unset: bool | None = None
    exclude_none: bool | None = None
    exclude_defaults: bool | None = None


# --- Type aliases -------------------------------------------------------------
type MethodType = Literal["GET", "PUT", "POST", "PATCH", "DELETE", "HEAD", "OPTIONS"]

type Decoder = Callable[[Response], object]

type EventHook = Callable[[Request], object] | Callable[[Response], object]
"""A sync hook, called with the request or the response."""

type AsyncEventHook = Callable[[Request], Awaitable[object]] | Callable[[Response], Awaitable[object]]
"""An async hook: like ``EventHook`` but must be an ``async def``."""


# --- httpx2's signatures ------------------------------------------------------
class _HttpxClientOptions(TypedDict, total=False):
    """The keyword arguments ``Client`` and ``AsyncClient`` share.

    They differ in ``transport``, ``mounts`` and ``event_hooks``, which take
    sync or async objects, so those live in ``HttpxClientOptions`` and
    ``AsyncHttpxClientOptions``.

    Every constructor parameter except ``base_url`` is included, deprecated ones
    too, so ``ClientX`` and ``AsyncClientX`` can forward ``**kwargs`` to httpx2
    unchanged. They take ``base_url`` as a parameter of their own.
    """

    auth: AuthTypes | None
    """Authentication to apply to every request.

    An ``Auth``, a (username, password) tuple, or a callable that signs each
    request.
    """

    params: QueryParamTypes | None
    """Query parameters to include in request URLs.

    A mapping, a list of pairs, a string, or ``QueryParams``.
    """

    headers: HeaderTypes | None
    """HTTP headers to include when sending requests.

    A mapping, a list of pairs, or ``Headers``.
    """

    cookies: CookieTypes | None
    """Cookie items to include when sending requests."""

    verify: bool | str | ssl.SSLContext
    """TLS verification: ``True``, ``False``, or an ``ssl.SSLContext``.

    ``True`` uses the system trust store, and ``False`` turns verification off.

    Deprecated: a CA-bundle path ``str`` still works but emits a
    ``DeprecationWarning``; build an ``ssl.SSLContext`` instead.
    """

    cert: CertTypes | None
    """Client certificate for TLS.

    A cert file, (cert, key), or (cert, key, password).

    Deprecated: emits a ``DeprecationWarning``. Build an ``ssl.SSLContext``,
    call ``.load_cert_chain()``, and pass it as ``verify``.
    """

    http1: bool
    """Enable or disable HTTP/1.1 support."""

    http2: bool
    """Enable or disable HTTP/2 support."""

    proxy: ProxyTypes | None
    """A proxy URL or configuration where all traffic should be routed."""

    timeout: TimeoutTypes
    """The default timeouts for requests.

    Seconds, ``None`` for none, a (connect, read, write, pool) tuple, or a
    ``Timeout``.
    """

    follow_redirects: bool
    """Whether to follow HTTP redirect responses."""

    limits: Limits
    """Connection pool limits configuration."""

    max_redirects: int
    """Maximum number of redirect responses to follow."""

    trust_env: bool
    """Enable or disable usage of environment variables for configuration."""

    default_encoding: str | Callable[[bytes], str | None]
    """Encoding for response text that has no charset."""


class HttpxClientOptions(_HttpxClientOptions, total=False):
    """Keyword arguments of ``Client.__init__``.

    ``ClientX.__init__`` takes them as ``**kwargs``.
    """

    mounts: Mapping[str, BaseTransport | None] | None
    """Transports for requests whose URLs match a pattern, keyed by pattern."""

    transport: BaseTransport | None
    """Transport instance used to send requests over the network."""

    event_hooks: Mapping[str, list[EventHook]] | None
    """Event hooks to call while requests and responses are processed.

    Supported hook types:
    - "request": called with a ``Request`` immediately before it is sent.
    - "response": called with a ``Response`` as soon as the response
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
    """Transports for requests whose URLs match a pattern, keyed by pattern."""

    transport: AsyncBaseTransport | None
    """Transport instance used to send requests over the network."""

    event_hooks: Mapping[str, list[AsyncEventHook]] | None
    """Async event hooks to call while requests and responses are processed.

    Supported hook types:
    - "request": called with a ``Request`` immediately before it is sent.
    - "response": called with a ``Response`` as soon as the response
      headers are received.

    Each value is a list of ``async`` callables, invoked in list order.

    Note:
        Response hooks run before the body is read. Avoid consuming the body or
        doing blocking work that depends on the full content.
    """


class BuildRequestKwargs(TypedDict, total=False):
    """Keyword arguments of ``build_request``, after ``method`` and ``url``.

    ``_builder.build_request`` fills the parts that carry an endpoint's
    arguments, and ``Endpoint.request_arguments`` adds ``timeout``. ClientX
    never sets ``cookies`` or ``extensions``: they're listed so the keys match
    ``build_request``'s parameters.
    """

    content: RequestContent | None
    """The raw body: ``str``, ``bytes``, or a sync or async iterable of bytes.

    A ``Body()`` parameter sets it.
    """

    data: RequestData | None
    """Form fields, form-encoded, or a multipart form with ``files``.

    ``Form()`` parameters set it.
    """

    files: RequestFiles | None
    """Files to upload in a multipart form.

    ``File()`` parameters set it.
    """

    json: Any | None
    """A JSON body.

    ``Json()`` parameters set it.
    """

    params: QueryParamTypes | None
    """Query parameters, merged with the client's.

    ``Query()`` parameters set it.
    """

    headers: HeaderTypes | None
    """HTTP headers, merged with the client's.

    ``Header()`` parameters set it.
    """

    cookies: CookieTypes | None
    """Cookies, merged with the client's.

    ClientX never sets it: there's no ``Cookie()`` helper.
    """

    timeout: TimeoutTypes | UseClientDefault
    """The request's timeout, or ``USE_CLIENT_DEFAULT`` for the client's.

    The endpoint's ``timeout=`` sets it.
    """

    extensions: RequestExtensions | None
    """Options for the transport, such as a ``trace`` callback.

    ClientX never sets it.
    """
