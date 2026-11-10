from __future__ import annotations

import copy
import inspect
from collections.abc import Sequence
from types import TracebackType
from typing import Any, ClassVar, Self, Unpack

from httpx2 import URL, Client, Response

from clientx._client_types import HttpxClientKwargs
from clientx._registry import endpoint_for
from clientx._version import __version__
from clientx.exceptions import EndpointNameConflictError, UnboundResourceError


class ClientX:
    """Base HTTP client wrapper for declarative ClientX API clients.

    Attributes:
        client: Underlying ``httpx2.Client`` instance used to build and send requests.
    """

    _default_user_agent: ClassVar[str] = f"ClientX/{__version__}"
    _user_agent: str
    client: Client
    # Internal state uses a ``__clientx_*__`` name, so it can't clash with an endpoint name.
    __clientx_raise_for_status__: bool

    def __init__(
        self,
        base_url: URL | str,
        *,
        user_agent: str | None = None,
        raise_for_status: bool = True,
        **client_kwargs: Unpack[HttpxClientKwargs],
    ):
        """Initialize a client with a base URL and optional ``httpx2.Client`` configuration.

        Args:
            base_url: Base URL used for all relative request paths.
            user_agent: Optional user agent header value. When ``None``, uses the default ClientX user agent.
            raise_for_status: Raise ``httpx2.HTTPStatusError`` when an endpoint gets a 4xx or 5xx
                response, before any decoder runs. An endpoint's own ``raise_for_status=`` overrides it.
            **client_kwargs: Additional keyword arguments passed directly to ``httpx2.Client``.
        """
        self.client = Client(base_url=URL(base_url), **client_kwargs)
        self.user_agent = user_agent
        self.__clientx_raise_for_status__ = raise_for_status

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Reject endpoints and resources named like something ``ClientX`` already has."""
        super().__init_subclass__(**kwargs)
        _check_member_names(cls, _CLIENTX_RESERVED_NAMES, base="ClientX")

    def __enter__(self) -> Self:
        """Enter the client context and return the active client instance.

        Returns:
            Self: The active client instance.
        """
        self.client.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        """Exit the client context and close the underlying ``httpx2.Client``.

        Args:
            exc_type: Exception type raised inside the context, if any.
            exc: Exception instance raised inside the context, if any.
            tb: Exception traceback, if any.

        Returns:
            bool: ``False`` to propagate exceptions from the context body.
        """
        self.client.__exit__(exc_type, exc, tb)
        return False

    def __repr__(self) -> str:
        """Return a concise debug representation of the client instance.

        Returns:
            String containing the class name, configured base URL, and active user agent.
        """
        return f"{type(self).__name__}(base_url={str(self.client.base_url)!r}, user_agent={self.user_agent!r})"

    @property
    def user_agent(self) -> str:
        """Return the active ``User-Agent`` header value for this client.

        Returns:
            The current user agent string.
        """
        return self._user_agent

    @user_agent.setter
    def user_agent(self, value: str | None):
        """Set the ``User-Agent`` header used by the underlying ``httpx2.Client``.

        Args:
            value: User agent string to apply. When ``None``, uses the default ClientX user agent.
        """
        self._user_agent = value or type(self)._default_user_agent
        self.client.headers.update({"User-Agent": self._user_agent})


class Resource:
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

    The prefix is joined to the path of each endpoint defined in the class body
    when the class is defined, so it's absolute: it doesn't depend on where the
    resource is mounted. A subclass without its own ``prefix`` or ``tags`` keeps
    its parent's. Internal state uses ``__clientx_*__`` names, so endpoint names
    such as ``send``, ``client``, or ``user_agent`` are free on a resource.
    """

    __clientx_prefix__: ClassVar[str] = ""
    __clientx_tags__: ClassVar[tuple[str, ...]] = ()
    __clientx_parent__: ClientX | Resource | None = None

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
        if prefix is not None:
            cls.__clientx_prefix__ = prefix
        if tags is not None:
            cls.__clientx_tags__ = tuple(tags)

        _check_member_names(cls, _RESOURCE_RESERVED_NAMES, base="Resource")
        for value in vars(cls).values():
            endpoint = endpoint_for(value)
            if endpoint is not None:
                endpoint.path = _join_path(cls.__clientx_prefix__, str(endpoint.path))
                endpoint.tags = list(dict.fromkeys([*cls.__clientx_tags__, *endpoint.tags]))

    def __set_name__(self, owner: type[Any], name: str) -> None:
        """Check that the resource is mounted on a ``ClientX`` or ``Resource`` subclass."""
        if not issubclass(owner, (ClientX, Resource)):
            raise TypeError(
                f"Resource '{type(self).__qualname__}' can only be mounted on a ClientX or Resource "
                f"subclass, not on '{owner.__qualname__}'."
            )

    def __get__(self, instance: ClientX | Resource | None, owner: type[Any] | None = None) -> Self:
        """Return a copy bound to ``instance``, or the resource itself on class access."""
        if instance is None:
            return self
        bound = copy.copy(self)
        bound.__clientx_parent__ = instance
        return bound

    def __repr__(self) -> str:
        """Return the resource class name and its prefix."""
        return f"{type(self).__qualname__}(prefix={type(self).__clientx_prefix__!r})"


# Names an endpoint or mounted resource can't use on each base class: everything
# the base defines, including the instance attributes it declares. Overriding them
# breaks the client; for example, `ClientX.__init__` sets `client` and `user_agent`.
_CLIENTX_RESERVED_NAMES = frozenset(dir(ClientX)) | frozenset(inspect.get_annotations(ClientX))
_RESOURCE_RESERVED_NAMES = frozenset(dir(Resource)) | frozenset(inspect.get_annotations(Resource))


def _check_member_names(cls: type, reserved: frozenset[str], *, base: str) -> None:
    """Raise if an endpoint or mounted resource in ``cls``'s body uses a reserved name."""
    for name, value in vars(cls).items():
        if name in reserved and (endpoint_for(value) is not None or isinstance(value, Resource)):
            raise EndpointNameConflictError(owner=cls, name=name, base=base)


def _join_path(prefix: str, path: str) -> str:
    """Join a resource prefix and an endpoint path with exactly one slash between them."""
    if not prefix:
        return path
    if not path:
        return prefix
    return prefix.rstrip("/") + "/" + path.lstrip("/")


def client_of(owner: object) -> ClientX:
    """Return the client an endpoint call goes through.

    Args:
        owner: The object the endpoint was called on: a ``ClientX`` instance or a
            resource bound to one (possibly through other resources).

    Raises:
        UnboundResourceError: If ``owner`` is a resource that isn't mounted on a client.
        TypeError: If ``owner`` is neither a client nor a resource.
    """
    current = owner
    while isinstance(current, Resource):
        parent = current.__clientx_parent__
        if parent is None:
            raise UnboundResourceError(type(current))
        current = parent
    if isinstance(current, ClientX):
        return current
    raise TypeError(
        f"Endpoints must be called on a ClientX instance or a mounted Resource, not on {type(owner).__name__!r}."
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
    request = client.client.build_request(method=method, url=path, **request_parts)
    return client.client.send(request, stream=stream)


__all__ = ["ClientX", "Resource"]
