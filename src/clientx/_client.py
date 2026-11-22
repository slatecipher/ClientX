from __future__ import annotations

from collections.abc import Sequence
from copy import copy
from typing import Any, ClassVar, Self, Unpack, cast

from httpx2 import URL, AsyncClient, Client, Headers

from clientx._class_setup import check_mount, parse_base_url, set_up_client, set_up_resource
from clientx._types import AsyncHttpxClientOptions, HeaderTypes, HttpxClientOptions
from clientx._version import __version__
from clientx.exceptions import DefinitionError

type EndpointOwner = ClientX | AsyncClientX | Resource | AsyncResource


# --- Clients ------------------------------------------------------------------
class _BaseClientX:
    # The class arguments: what a client uses when its caller doesn't say.
    __clientx_base_url__: ClassVar[URL | None] = None
    __clientx_user_agent__: ClassVar[str] = f"ClientX/{__version__}"
    __clientx_raise_for_status__: bool = True
    __clientx_validate_arguments__: bool = False

    def __repr__(self) -> str:
        client = cast("ClientX | AsyncClientX", self)
        return (
            f"{type(self).__qualname__}(base_url={_masked(client.base_url)!r}, "
            f"user_agent={client.headers.get('User-Agent')!r})"
        )


def _masked(url: URL) -> str:
    """Return ``url`` as text with any password masked, for a repr."""
    text = str(url)
    if not url.password:
        return text
    userinfo = url.userinfo.decode("ascii")
    username = userinfo.split(":", 1)[0]
    return text.replace(f"//{userinfo}@", f"//{username}:[redacted]@", 1)


class ClientX(_BaseClientX, Client):
    """Base class for an HTTP API client: subclass it and declare endpoints.

    An endpoint is a ``def`` method with an empty body and a ``clientx.method``
    decorator. Its signature and annotations say how to build the request and
    decode the response. A ``ClientX`` is an ``httpx2.Client``, so it's
    configured, used and closed like one::

        class UsersAPI(ClientX, base_url="https://api.example.com"):
            @method.get("/users/{user_id}")
            def get_user(self, user_id: int) -> User: ...

        with UsersAPI() as api:
            user = api.get_user(1)
    """

    # Which kind of class this is: `def` endpoints and resources. `_class_setup`
    # reads it.
    __clientx_is_async__: ClassVar[bool] = False

    def __init__(
        self,
        base_url: URL | str | None = None,
        *,
        user_agent: str | None = None,
        raise_for_status: bool | None = None,
        validate_arguments: bool = False,
        **kwargs: Unpack[HttpxClientOptions],
    ) -> None:
        """Initialize with a base URL and ``httpx2.Client`` options.

        Args:
            base_url: Base URL used for all relative request paths. When
                ``None``, the class's ``base_url=`` class argument.
            user_agent: The ``User-Agent`` header to send. When ``None``, a
                ``User-Agent`` given in ``headers=`` is kept, or else the
                class's default: its ``user_agent=`` class argument, or
                ``ClientX/<version>``.
            raise_for_status: Raise ``httpx2.HTTPStatusError`` when an endpoint
                gets a 4xx or 5xx response, before any decoder runs. On when
                ``None``. An endpoint's own ``raise_for_status=`` overrides it.
            validate_arguments: Check the arguments of each call against their
                annotations, strictly, before anything is sent, and raise
                ``ArgumentError`` if one doesn't fit. A helper's constraints,
                such as ``Query(ge=1)``, are checked too.
            **kwargs: Additional keyword arguments passed directly to
                ``httpx2.Client``.

        Raises:
            TypeError: If there's no base URL, here or on the class.
            ValueError: If ``base_url`` isn't an absolute URL, with a scheme and
                a host.
        """
        super().__init__(base_url=_base_url(type(self), base_url), **kwargs)
        _configure(
            self,
            user_agent=user_agent,
            headers=kwargs.get("headers"),
            raise_for_status=raise_for_status,
            validate_arguments=validate_arguments,
        )

    def __init_subclass__(
        cls, *, base_url: URL | str | None = None, user_agent: str | None = None, **kwargs: Any
    ) -> None:
        """Check the class, store its class arguments, and set up its endpoints.

        An endpoint or mounted resource can't use a name ``ClientX`` already
        uses, which includes all of ``httpx2.Client``'s, such as ``get`` or
        ``send``. Those names are free on a ``Resource``. The ``base_url=`` and
        ``user_agent=`` class arguments are used unless the caller gives its
        own. A subclass without one keeps its parent's, and a direct subclass
        has no base URL and sends ``ClientX/<version>``.

        Raises:
            DefinitionError: If ``base_url`` isn't an absolute URL, with a
                scheme and a host, or the class breaks a rule for endpoints or
                resources.
        """
        super().__init_subclass__(**kwargs)
        set_up_client(cls, base=ClientX, base_url=base_url, user_agent=user_agent)


class AsyncClientX(_BaseClientX, AsyncClient):
    """Base class for an async HTTP API client, with ``async def`` endpoints.

    It works like ``ClientX``, but an ``AsyncClientX`` is an
    ``httpx2.AsyncClient``, so it's used with ``async with`` and closed with
    ``aclose()``.
    """

    # Which kind of class this is: `async def` endpoints and resources.
    # `_class_setup` reads it.
    __clientx_is_async__: ClassVar[bool] = True

    def __init__(
        self,
        base_url: URL | str | None = None,
        *,
        user_agent: str | None = None,
        raise_for_status: bool | None = None,
        validate_arguments: bool = False,
        **kwargs: Unpack[AsyncHttpxClientOptions],
    ) -> None:
        """Initialize with a base URL and ``httpx2.AsyncClient`` options.

        Takes the same arguments as ``ClientX``, except that ``transport`` and
        ``mounts`` take async transports, and event hooks must be ``async``
        functions.
        """
        super().__init__(base_url=_base_url(type(self), base_url), **kwargs)
        _configure(
            self,
            user_agent=user_agent,
            headers=kwargs.get("headers"),
            raise_for_status=raise_for_status,
            validate_arguments=validate_arguments,
        )

    def __init_subclass__(
        cls, *, base_url: URL | str | None = None, user_agent: str | None = None, **kwargs: Any
    ) -> None:
        """Check the class and set up its endpoints, like ``ClientX``."""
        super().__init_subclass__(**kwargs)
        set_up_client(cls, base=AsyncClientX, base_url=base_url, user_agent=user_agent)


def _base_url(cls: type[ClientX | AsyncClientX], base_url: URL | str | None) -> URL:
    """Return the base URL given, or else the class's.

    Raises:
        TypeError: If there's neither, as for a missing argument.
        ValueError: If the one given isn't an absolute URL.
    """
    if base_url is not None:
        return parse_base_url(base_url)
    if cls.__clientx_base_url__ is not None:
        return cls.__clientx_base_url__
    name, base = cls.__qualname__, ("AsyncClientX" if cls.__clientx_is_async__ else "ClientX")
    raise TypeError(
        f'{name} needs a base URL: pass one, as in {name}("https://api.example.com"), or set it in the class '
        f'statement, as in class {name}({base}, base_url="https://api.example.com").'
    )


def _configure(
    client: ClientX | AsyncClientX,
    *,
    user_agent: str | None,
    headers: HeaderTypes | None,
    raise_for_status: bool | None,
    validate_arguments: bool,
) -> None:
    # httpx2 always sets its own User-Agent, so read the caller's from
    # `headers=`, not from `client.headers`.
    client.headers["User-Agent"] = (
        user_agent or Headers(headers).get("User-Agent") or type(client).__clientx_user_agent__
    )
    if raise_for_status is not None:
        client.__clientx_raise_for_status__ = raise_for_status
    client.__clientx_validate_arguments__ = validate_arguments


# --- Resources ----------------------------------------------------------------
class _BaseResource:
    """Shared base of ``Resource`` and ``AsyncResource``: prefix, tags, parent.

    Internal state uses ``__clientx_*__`` names, so names ``ClientX`` uses, such
    as ``close``, are free for endpoints on a resource.
    """

    __clientx_prefix__: ClassVar[str] = ""
    __clientx_tags__: ClassVar[tuple[str, ...]] = ()
    __clientx_parent__: ClientX | AsyncClientX | _BaseResource | None = None
    # Set by `Resource` and `AsyncResource`, as on the clients.
    __clientx_is_async__: ClassVar[bool]

    def __set_name__(self, owner: type[Any], name: str) -> None:
        """Check that the resource is mounted on its own kind of class."""
        check_mount(type(self).__qualname__, is_async=self.__clientx_is_async__, owner=owner)

    def __get__(self, instance: ClientX | AsyncClientX | _BaseResource | None, owner: type[Any] | None = None) -> Self:
        """Return a copy bound to ``instance``, or ``self`` on class access."""
        if instance is None:
            return self
        bound = copy(self)
        bound.__clientx_parent__ = instance
        return bound

    def __repr__(self) -> str:
        return f"{type(self).__qualname__}(prefix={type(self).__clientx_prefix__!r})"


class Resource(_BaseResource):
    """Base class for a group of endpoints under a path prefix.

    Declare endpoints as on a ``ClientX``, and mount an instance as a class
    attribute of a client::

        class Users(Resource, prefix="/users"):
            @method.get("/{user_id}")
            def get(self, user_id: int) -> User: ...

        class UsersAPI(ClientX):
            users = Users()

    ``api.users.get(1)`` then calls ``/users/1``. A resource can be mounted on
    another resource, but prefixes don't add up: each is the full prefix.
    ``ClientX``'s names, such as ``get``, are free for a resource's endpoints.
    """

    __clientx_is_async__: ClassVar[bool] = False

    def __init_subclass__(cls, *, prefix: str | None = None, tags: Sequence[str] | None = None, **kwargs: Any) -> None:
        """Check the class, and apply its prefix and tags to its endpoints.

        The ``prefix=`` class argument, such as ``"/users"``, is joined onto
        each endpoint's path; a subclass without one keeps its parent's.
        ``tags=`` are added to the parent class's tags, then go before each
        endpoint's own, each tag once.
        """
        super().__init_subclass__(**kwargs)
        set_up_resource(cls, base=Resource, prefix=prefix, tags=tags)


class AsyncResource(_BaseResource):
    """Base class for a group of ``async def`` endpoints, like ``Resource``.

    Mount it on an ``AsyncClientX`` or another ``AsyncResource``.
    """

    __clientx_is_async__: ClassVar[bool] = True

    def __init_subclass__(cls, *, prefix: str | None = None, tags: Sequence[str] | None = None, **kwargs: Any) -> None:
        """Check the class and apply its prefix and tags, like ``Resource``."""
        super().__init_subclass__(**kwargs)
        set_up_resource(cls, base=AsyncResource, prefix=prefix, tags=tags)


# --- Finding a call's client --------------------------------------------------
def client_of[C: ClientX | AsyncClientX](owner: object, kind: type[C]) -> C:
    """Return the client an endpoint call on ``owner`` goes through.

    Args:
        owner: The object the endpoint was called on: a client, or a resource
            mounted on one (possibly through other resources).
        kind: The client class the endpoint needs: ``ClientX`` for a ``def``
            endpoint, ``AsyncClientX`` for an ``async def`` one.

    Raises:
        DefinitionError: If ``owner`` is a resource that isn't mounted on a
            client, or isn't a ``kind`` instance or a resource mounted on one.
    """
    current = owner
    while isinstance(current, _BaseResource):
        if current.__clientx_parent__ is None:
            name = type(current).__qualname__
            raise DefinitionError(
                f"Resource '{name}' isn't mounted on a client. Mount an instance as a class "
                f"attribute of a ClientX subclass (for example, `items = {name}()`) and call "
                "its endpoints through a client instance (`client.items.<endpoint>(...)`)."
            )
        current = current.__clientx_parent__
    if isinstance(current, kind):
        return current
    raise DefinitionError(
        f"The endpoint must be called on an instance of {kind.__name__} or a resource mounted on one, "
        f"not on {type(owner).__qualname__!r}."
    )
