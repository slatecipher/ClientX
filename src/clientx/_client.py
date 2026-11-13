from __future__ import annotations

import copy
import inspect
from collections.abc import Sequence
from types import TracebackType
from typing import Any, ClassVar, Self, Unpack

from httpx2 import URL, AsyncClient, Client, Headers, Response

from clientx._client_types import AsyncHttpxClientKwargs, HeaderTypes, HttpxClientKwargs
from clientx._registry import endpoint_for
from clientx._version import __version__
from clientx.exceptions import EndpointNameConflictError, EndpointSignatureError, UnboundResourceError


class _BaseClientX[HttpClient: Client | AsyncClient]:
    """What ``ClientX`` and ``AsyncClientX`` share: class defaults, settings, and ``repr``.

    Every public attribute is a name endpoints can't use, so internal state uses
    ``__clientx_*__`` names, and the httpx2 client isn't public.
    """

    __clientx_client__: HttpClient
    __clientx_base_url__: ClassVar[URL | str | None] = None
    __clientx_user_agent__: ClassVar[str] = f"ClientX/{__version__}"
    __clientx_raise_for_status__: bool
    __clientx_validate_arguments__: bool

    def __repr__(self) -> str:
        """Return a concise debug representation of the client instance.

        Returns:
            String containing the class name, configured base URL, and ``User-Agent``.
        """
        client = self.__clientx_client__
        return f"{type(self).__name__}(base_url={str(client.base_url)!r}, user_agent={client.headers['User-Agent']!r})"


class ClientX(_BaseClientX[Client]):
    """Base HTTP client wrapper for declarative ClientX API clients.

    A subclass can ship its own base URL and ``User-Agent`` with class arguments, so
    callers can create it without arguments::

        class ExampleAPI(ClientX, base_url="https://api.example.com", user_agent="example-api/1.0"):
            ...

        api = ExampleAPI()  # arguments given here win over the class's

    Requests go through an internal ``httpx2.Client``. Close its connections with a
    ``with`` block or ``close()``. Its endpoints are plain ``def`` methods; for
    ``async def`` endpoints, subclass ``AsyncClientX``.
    """

    def __init__(
        self,
        base_url: URL | str | None = None,
        *,
        user_agent: str | None = None,
        raise_for_status: bool = True,
        validate_arguments: bool = False,
        **client_kwargs: Unpack[HttpxClientKwargs],
    ):
        """Initialize a client with a base URL and optional ``httpx2.Client`` configuration.

        Args:
            base_url: Base URL used for all relative request paths. Defaults to the class's
                ``base_url=`` class argument; one of the two is required.
            user_agent: The ``User-Agent`` header to send. When ``None``, a ``User-Agent`` given in
                ``headers=`` is kept, or else the class's default: its ``user_agent=`` class
                argument, or ``ClientX/<version>``.
            raise_for_status: Raise ``httpx2.HTTPStatusError`` when an endpoint gets a 4xx or 5xx
                response, before any decoder runs. An endpoint's own ``raise_for_status=`` overrides it.
            validate_arguments: Check each argument against its parameter's annotation before
                sending, and raise ``ArgumentValidationError`` if it doesn't match. Off by default.
                An endpoint's own ``validate_arguments=`` overrides it.
            **client_kwargs: Additional keyword arguments passed directly to ``httpx2.Client``.
        """
        self.__clientx_client__ = Client(base_url=_base_url(type(self), base_url, base="ClientX"), **client_kwargs)
        _configure(
            self,
            user_agent=user_agent,
            headers=client_kwargs.get("headers"),
            raise_for_status=raise_for_status,
            validate_arguments=validate_arguments,
        )

    def __init_subclass__(
        cls, *, base_url: URL | str | None = None, user_agent: str | None = None, **kwargs: Any
    ) -> None:
        """Set the class's defaults, and reject members named like something ``ClientX`` already has.

        Args:
            base_url: The base URL this client uses unless the caller gives one. Defaults to
                the parent class's; without one anywhere, the caller must pass it.
            user_agent: The ``User-Agent`` this client sends unless the caller gives one.
                Defaults to the parent class's, ``ClientX/<version>`` for a direct subclass.
            **kwargs: Forwarded to ``object.__init_subclass__``.
        """
        super().__init_subclass__(**kwargs)
        _set_up_subclass(cls, base_url=base_url, user_agent=user_agent, base="ClientX")

    def __enter__(self) -> Self:
        """Enter the client context and return the active client instance.

        Returns:
            Self: The active client instance.
        """
        self.__clientx_client__.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit the client context and close the underlying ``httpx2.Client``.

        An exception raised in the ``with`` block always propagates. The ``None`` return
        type tells type checkers so: with ``bool``, they would assume the block could
        swallow an exception, and report a function that returns inside it as missing a
        return statement.

        Args:
            exc_type: Exception type raised inside the context, if any.
            exc: Exception instance raised inside the context, if any.
            tb: Exception traceback, if any.
        """
        self.__clientx_client__.__exit__(exc_type, exc, tb)

    def close(self) -> None:
        """Close the client's connections. A ``with`` block does this for you."""
        self.__clientx_client__.close()


class AsyncClientX(_BaseClientX[AsyncClient]):
    """Base HTTP client for declarative API clients whose endpoints are ``async def`` methods.

    It works like ``ClientX``, with the same class arguments and options, but sends
    requests through an internal ``httpx2.AsyncClient``, and its endpoints are awaited::

        class ExampleAPI(AsyncClientX, base_url="https://api.example.com"):
            @get("/users/{user_id}", decoder=ModelDecoder(User))
            async def retrieve(self, user_id: int) -> User: ...

        async with ExampleAPI() as api:
            user = await api.retrieve(42)

    Close its connections with an ``async with`` block or ``aclose()``.
    """

    def __init__(
        self,
        base_url: URL | str | None = None,
        *,
        user_agent: str | None = None,
        raise_for_status: bool = True,
        validate_arguments: bool = False,
        **client_kwargs: Unpack[AsyncHttpxClientKwargs],
    ):
        """Initialize a client with a base URL and optional ``httpx2.AsyncClient`` configuration.

        Args:
            base_url: Base URL used for all relative request paths. Defaults to the class's
                ``base_url=`` class argument; one of the two is required.
            user_agent: The ``User-Agent`` header to send. When ``None``, a ``User-Agent`` given in
                ``headers=`` is kept, or else the class's default: its ``user_agent=`` class
                argument, or ``ClientX/<version>``.
            raise_for_status: Raise ``httpx2.HTTPStatusError`` when an endpoint gets a 4xx or 5xx
                response, before any decoder runs. An endpoint's own ``raise_for_status=`` overrides it.
            validate_arguments: Check each argument against its parameter's annotation before
                sending, and raise ``ArgumentValidationError`` if it doesn't match. Off by default.
                An endpoint's own ``validate_arguments=`` overrides it.
            **client_kwargs: Additional keyword arguments passed directly to ``httpx2.AsyncClient``.
                Its ``transport`` and ``mounts`` take async transports, and its event hooks must be
                ``async`` functions.
        """
        self.__clientx_client__ = AsyncClient(
            base_url=_base_url(type(self), base_url, base="AsyncClientX"), **client_kwargs
        )
        _configure(
            self,
            user_agent=user_agent,
            headers=client_kwargs.get("headers"),
            raise_for_status=raise_for_status,
            validate_arguments=validate_arguments,
        )

    def __init_subclass__(
        cls, *, base_url: URL | str | None = None, user_agent: str | None = None, **kwargs: Any
    ) -> None:
        """Set the class's defaults, and reject members named like something ``AsyncClientX`` already has.

        Args:
            base_url: The base URL this client uses unless the caller gives one. Defaults to
                the parent class's; without one anywhere, the caller must pass it.
            user_agent: The ``User-Agent`` this client sends unless the caller gives one.
                Defaults to the parent class's, ``ClientX/<version>`` for a direct subclass.
            **kwargs: Forwarded to ``object.__init_subclass__``.
        """
        super().__init_subclass__(**kwargs)
        _set_up_subclass(cls, base_url=base_url, user_agent=user_agent, base="AsyncClientX")

    async def __aenter__(self) -> Self:
        """Enter the client context and return the active client instance.

        Returns:
            Self: The active client instance.
        """
        await self.__clientx_client__.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit the client context and close the underlying ``httpx2.AsyncClient``.

        An exception raised in the ``async with`` block always propagates, as with ``ClientX``.

        Args:
            exc_type: Exception type raised inside the context, if any.
            exc: Exception instance raised inside the context, if any.
            tb: Exception traceback, if any.
        """
        await self.__clientx_client__.__aexit__(exc_type, exc, tb)

    async def aclose(self) -> None:
        """Close the client's connections. An ``async with`` block does this for you."""
        await self.__clientx_client__.aclose()


class _BaseResource:
    """What ``Resource`` and ``AsyncResource`` share: the prefix, the tags, and binding to a parent.

    Internal state uses ``__clientx_*__`` names, so names ``ClientX`` uses, such as
    ``close``, are free for endpoints on a resource.
    """

    __clientx_prefix__: ClassVar[str] = ""
    __clientx_tags__: ClassVar[tuple[str, ...]] = ()
    __clientx_parent__: ClientX | AsyncClientX | _BaseResource | None = None

    def __get__(self, instance: ClientX | AsyncClientX | _BaseResource | None, owner: type[Any] | None = None) -> Self:
        """Return a copy bound to ``instance``, or the resource itself on class access."""
        if instance is None:
            return self
        bound = copy.copy(self)
        bound.__clientx_parent__ = instance
        return bound

    def __repr__(self) -> str:
        """Return the resource class name and its prefix."""
        return f"{type(self).__qualname__}(prefix={type(self).__clientx_prefix__!r})"


class Resource(_BaseResource):
    """A group of endpoints with a shared path prefix and tags, mounted on a client.

    Subclass it, declare endpoints with the verb decorators, and mount an instance
    as a class attribute of a ``ClientX`` subclass (or of another ``Resource``, to
    nest them). Its endpoints then send through that client's connection::

        class Users(Resource, prefix="/users", tags=["users"]):
            @get("/{user_id}", decoder=ModelDecoder(User))
            def retrieve(self, user_id: int) -> User: ...

        class ExampleAPI(ClientX):
            users = Users()

        ExampleAPI("https://api.example.com").users.retrieve(42)  # GET /users/42

    Its endpoints are ``def`` methods; for ``async def`` endpoints on an ``AsyncClientX``,
    subclass ``AsyncResource``. The prefix is joined to the path of each endpoint defined
    in the class body when the class is defined, so it's absolute: it doesn't depend on
    where the resource is mounted. A subclass without its own ``prefix`` or ``tags`` keeps
    its parent's.
    """

    def __init_subclass__(cls, *, prefix: str | None = None, tags: Sequence[str] | None = None, **kwargs: Any) -> None:
        """Apply the class's prefix and tags to the endpoints defined in its body.

        Args:
            prefix: Path prefix for this class's endpoints, such as ``"/users"``.
                Defaults to the parent class's prefix.
            tags: Tags added before each endpoint's own tags. Defaults to the
                parent class's tags.
            **kwargs: Forwarded to ``object.__init_subclass__``.
        """
        super().__init_subclass__(**kwargs)
        _set_up_resource(cls, prefix=prefix, tags=tags, base="Resource")

    def __set_name__(self, owner: type[Any], name: str) -> None:
        """Check that the resource is mounted on a ``ClientX`` or ``Resource`` subclass."""
        _check_mount(self, owner, base="Resource")


class AsyncResource(_BaseResource):
    """A group of ``async def`` endpoints with a shared path prefix and tags, mounted on an ``AsyncClientX``.

    It works like ``Resource``, for an ``AsyncClientX`` (or another ``AsyncResource``)::

        class Users(AsyncResource, prefix="/users", tags=["users"]):
            @get("/{user_id}", decoder=ModelDecoder(User))
            async def retrieve(self, user_id: int) -> User: ...

        class ExampleAPI(AsyncClientX):
            users = Users()

        await ExampleAPI("https://api.example.com").users.retrieve(42)  # GET /users/42
    """

    def __init_subclass__(cls, *, prefix: str | None = None, tags: Sequence[str] | None = None, **kwargs: Any) -> None:
        """Apply the class's prefix and tags to the endpoints defined in its body.

        Args:
            prefix: Path prefix for this class's endpoints, such as ``"/users"``.
                Defaults to the parent class's prefix.
            tags: Tags added before each endpoint's own tags. Defaults to the
                parent class's tags.
            **kwargs: Forwarded to ``object.__init_subclass__``.
        """
        super().__init_subclass__(**kwargs)
        _set_up_resource(cls, prefix=prefix, tags=tags, base="AsyncResource")

    def __set_name__(self, owner: type[Any], name: str) -> None:
        """Check that the resource is mounted on an ``AsyncClientX`` or ``AsyncResource`` subclass."""
        _check_mount(self, owner, base="AsyncResource")


def _reserved_names(base: type) -> frozenset[str]:
    """Return the names an endpoint or mounted resource can't use on ``base``: everything it defines.

    That includes the instance attributes it declares, on it or on its bases. Overriding them
    breaks the client; for example, an endpoint named ``close`` would replace ``ClientX.close``.
    """
    return frozenset(dir(base)).union(*(inspect.get_annotations(cls) for cls in base.__mro__))


_RESERVED_NAMES = {base.__name__: _reserved_names(base) for base in (ClientX, AsyncClientX, Resource, AsyncResource)}

# Each base, the kind of endpoint it holds, and the base for the other kind. A resource mounts on a
# client of its own kind, or on another resource of its kind.
_ASYNC_BASES = frozenset({"AsyncClientX", "AsyncResource"})
_OTHER_KIND = {
    "ClientX": "AsyncClientX",
    "AsyncClientX": "ClientX",
    "Resource": "AsyncResource",
    "AsyncResource": "Resource",
}


def _base_url(cls: type[ClientX | AsyncClientX], base_url: URL | str | None, *, base: str) -> URL:
    """Return the base URL to use: the one given, or else the class's. Raise if there's neither."""
    base_url = cls.__clientx_base_url__ if base_url is None else base_url
    if base_url is None:
        name = cls.__name__
        raise TypeError(
            f'{name} needs a base URL: pass one, as in {name}("https://api.example.com"), or set it in '
            f'the class statement, as in class {name}({base}, base_url="https://api.example.com").'
        )
    return URL(base_url)


def _configure(
    client: ClientX | AsyncClientX,
    *,
    user_agent: str | None,
    headers: HeaderTypes | None,
    raise_for_status: bool,
    validate_arguments: bool,
) -> None:
    """Set a new client's ``User-Agent`` and its settings."""
    # A User-Agent passed in `headers=` is the caller's choice too; only `user_agent=` overrides it.
    client.__clientx_client__.headers["User-Agent"] = (
        user_agent or Headers(headers).get("User-Agent") or type(client).__clientx_user_agent__
    )
    client.__clientx_raise_for_status__ = raise_for_status
    client.__clientx_validate_arguments__ = validate_arguments


def _set_up_subclass(
    cls: type[ClientX | AsyncClientX], *, base_url: URL | str | None, user_agent: str | None, base: str
) -> None:
    """Apply a client subclass's class arguments, and check its members."""
    if issubclass(cls, ClientX) and issubclass(cls, AsyncClientX):
        raise TypeError(f"'{cls.__qualname__}' can't subclass both ClientX and AsyncClientX: choose one.")
    if base_url is not None:
        cls.__clientx_base_url__ = base_url
    if user_agent is not None:
        cls.__clientx_user_agent__ = user_agent
    _check_member_names(cls, _RESERVED_NAMES[base], base=base)
    _check_endpoint_kinds(cls, base=base)
    _check_path_helpers(cls)


def _set_up_resource(
    cls: type[Resource | AsyncResource], *, prefix: str | None, tags: Sequence[str] | None, base: str
) -> None:
    """Apply a resource subclass's prefix and tags to the endpoints in its body, and check its members."""
    if issubclass(cls, Resource) and issubclass(cls, AsyncResource):
        raise TypeError(f"'{cls.__qualname__}' can't subclass both Resource and AsyncResource: choose one.")
    if prefix is not None:
        cls.__clientx_prefix__ = prefix
    if tags is not None:
        cls.__clientx_tags__ = tuple(tags)

    _check_member_names(cls, _RESERVED_NAMES[base], base=base)
    _check_endpoint_kinds(cls, base=base)
    for value in vars(cls).values():
        endpoint = endpoint_for(value)
        if endpoint is not None:
            endpoint.path = _join_path(cls.__clientx_prefix__, str(endpoint.path))
            endpoint.tags = list(dict.fromkeys([*cls.__clientx_tags__, *endpoint.tags]))
    # After the prefix is joined, since it can add the placeholder a PathParam() parameter needs.
    _check_path_helpers(cls)


def _check_mount(resource: Resource | AsyncResource, owner: type[Any], *, base: str) -> None:
    """Raise if ``resource`` (a ``base`` instance) is mounted on anything but a client or resource of its kind."""
    is_async = base in _ASYNC_BASES
    clients, resources = (AsyncClientX, AsyncResource) if is_async else (ClientX, Resource)
    if issubclass(owner, (clients, resources)):
        return
    message = (
        f"{base} '{type(resource).__qualname__}' can only be mounted on a{'n' if is_async else ''} "
        f"{clients.__name__} or {resources.__name__} subclass, not on '{owner.__qualname__}'."
    )
    if issubclass(owner, (_BaseClientX, _BaseResource)):
        message += (
            f" For {'a' if is_async else 'an'} {_OTHER_KIND[clients.__name__]}, subclass {_OTHER_KIND[base]} instead."
        )
    raise TypeError(message)


def _check_member_names(cls: type, reserved: frozenset[str], *, base: str) -> None:
    """Raise if an endpoint or mounted resource in ``cls``'s body uses a reserved name."""
    for name, value in vars(cls).items():
        if name in reserved and (endpoint_for(value) is not None or isinstance(value, _BaseResource)):
            raise EndpointNameConflictError(owner=cls, name=name, base=base)


def _check_endpoint_kinds(cls: type, *, base: str) -> None:
    """Raise if an endpoint in ``cls``'s body is the wrong kind for ``base``.

    ``ClientX`` and ``Resource`` send with a sync ``httpx2.Client``, so their endpoints are
    ``def`` methods; ``AsyncClientX`` and ``AsyncResource`` endpoints are ``async def`` methods.
    Endpoints inherited from a base class were checked when it was defined, and a mounted
    resource's kind was checked when it was mounted.
    """
    is_async = base in _ASYNC_BASES
    for value in vars(cls).values():
        endpoint = endpoint_for(value)
        if endpoint is not None and endpoint.is_async != is_async:
            kind, fix = ("`async def`", "`def`") if endpoint.is_async else ("a plain `def`", "`async def`")
            raise EndpointSignatureError(
                endpoint.func,
                f"is {kind}, so it can't be an endpoint of '{cls.__qualname__}', a{'n' if is_async else ''} {base} "
                "subclass. "
                f"Define it with {fix}, or subclass {_OTHER_KIND[base]} instead",
            )


def _check_path_helpers(cls: type) -> None:
    """Raise if an endpoint in ``cls``'s body marks a parameter ``PathParam()`` that its path has no placeholder for."""
    for value in vars(cls).values():
        if (endpoint := endpoint_for(value)) is not None:
            endpoint.check_path_helpers()


def _join_path(prefix: str, path: str) -> str:
    """Join a resource prefix and an endpoint path with exactly one slash between them."""
    if not prefix:
        return path
    if not path:
        return prefix
    return prefix.rstrip("/") + "/" + path.lstrip("/")


def _root_of(owner: object) -> object:
    """Walk from a resource up its parents to the object it's mounted on, or return ``owner`` itself."""
    current = owner
    while isinstance(current, _BaseResource):
        parent = current.__clientx_parent__
        if parent is None:
            raise UnboundResourceError(type(current))
        current = parent
    return current


def client_of(owner: object) -> ClientX:
    """Return the client a ``def`` endpoint's call goes through.

    Args:
        owner: The object the endpoint was called on: a ``ClientX`` instance or a
            resource bound to one (possibly through other resources).

    Raises:
        UnboundResourceError: If ``owner`` is a resource that isn't mounted on a client.
        TypeError: If ``owner`` is neither a ``ClientX`` nor a resource mounted on one.
    """
    root = _root_of(owner)
    if isinstance(root, ClientX):
        return root
    raise TypeError(
        f"`def` endpoints must be called on a ClientX instance or a Resource mounted on one, "
        f"not on {type(owner).__name__!r}."
    )


def async_client_of(owner: object) -> AsyncClientX:
    """Return the client an ``async def`` endpoint's call goes through.

    Args:
        owner: The object the endpoint was called on: an ``AsyncClientX`` instance or a
            resource bound to one (possibly through other resources).

    Raises:
        UnboundResourceError: If ``owner`` is a resource that isn't mounted on a client.
        TypeError: If ``owner`` is neither an ``AsyncClientX`` nor a resource mounted on one.
    """
    root = _root_of(owner)
    if isinstance(root, AsyncClientX):
        return root
    raise TypeError(
        f"`async def` endpoints must be called on an AsyncClientX instance or a Resource mounted on one, "
        f"not on {type(owner).__name__!r}."
    )


def send_request(
    client: ClientX, method: str, path: URL | str, *, stream: bool = False, **request_parts: Any
) -> Response:
    """Build and send one request on ``client``'s underlying ``httpx2.Client``.

    Endpoint wrappers call this for every request. It's a module function rather
    than a ``ClientX`` method because every attribute on ``ClientX`` is a name that
    endpoints can't use; as a function, it leaves names such as ``send`` free.

    Args:
        client: The ClientX instance whose ``httpx2.Client`` sends the request.
        method: HTTP method name, such as ``"GET"`` or ``"POST"``.
        path: Request URL path or URL object relative to ``base_url`` when applicable.
        stream: Whether to stream the response body instead of eagerly reading it.
        **request_parts: Additional request options forwarded to ``httpx2.Client.build_request``.

    Returns:
        The HTTP response returned by ``httpx2.Client.send``.
    """
    request = client.__clientx_client__.build_request(method=method, url=path, **request_parts)
    return client.__clientx_client__.send(request, stream=stream)


async def asend_request(
    client: AsyncClientX, method: str, path: URL | str, *, stream: bool = False, **request_parts: Any
) -> Response:
    """Build and send one request on ``client``'s underlying ``httpx2.AsyncClient``.

    The ``async`` counterpart of ``send_request``, for ``async def`` endpoints.

    Args:
        client: The AsyncClientX instance whose ``httpx2.AsyncClient`` sends the request.
        method: HTTP method name, such as ``"GET"`` or ``"POST"``.
        path: Request URL path or URL object relative to ``base_url`` when applicable.
        stream: Whether to stream the response body instead of eagerly reading it.
        **request_parts: Additional request options forwarded to ``httpx2.AsyncClient.build_request``.

    Returns:
        The HTTP response returned by ``httpx2.AsyncClient.send``.
    """
    request = client.__clientx_client__.build_request(method=method, url=path, **request_parts)
    return await client.__clientx_client__.send(request, stream=stream)


__all__ = ["AsyncClientX", "AsyncResource", "ClientX", "Resource"]
