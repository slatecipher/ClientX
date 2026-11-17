from __future__ import annotations

from collections.abc import Sequence
from copy import copy
from typing import Any, ClassVar, Self, Unpack

from httpx2 import URL, AsyncClient, Client, Headers

from clientx._class_setup import check_mount, set_up_client, set_up_resource
from clientx._types import AsyncHttpxClientOptions, HeaderTypes, HttpxClientOptions
from clientx._version import __version__

type EndpointOwner = ClientX | AsyncClientX | Resource | AsyncResource


class _BaseClientX:
    __clientx_user_agent__: ClassVar[str] = f"ClientX/{__version__}"
    __clientx_raise_for_status__: bool = True
    __clientx_validate_arguments__: bool = False


class ClientX(_BaseClientX, Client):
    # Which kind of class this is: `def` endpoints and resources. `_class_setup` reads it.
    __clientx_is_async__: ClassVar[bool] = False

    def __init__(
        self,
        base_url: URL | str,
        *,
        user_agent: str | None = None,
        raise_for_status: bool | None = None,
        validate_arguments: bool | None = None,
        **kwargs: Unpack[HttpxClientOptions],
    ) -> None:
        """Initialize a client with a base URL and optional ``httpx2.Client`` configuration.

        Args:
            base_url: Base URL used for all relative request paths.
            user_agent: The ``User-Agent`` header to send. When ``None``, a ``User-Agent`` given in
                ``headers=`` is kept, or else the class's default: its ``user_agent=`` class
                argument, or ``ClientX/<version>``.
            raise_for_status: Raise ``httpx2.HTTPStatusError`` when an endpoint gets a 4xx or 5xx
                response, before any decoder runs. On when ``None``. An endpoint's own
                ``raise_for_status=`` overrides it.
            validate_arguments: Check each argument against its parameter's annotation before
                sending, and raise if it doesn't match. Off when ``None``. An endpoint's own
                ``validate_arguments=`` overrides it.
            **kwargs: Additional keyword arguments passed directly to ``httpx2.Client``.
        """
        super().__init__(base_url=base_url, **kwargs)
        _configure(
            self,
            user_agent=user_agent,
            headers=kwargs.get("headers"),
            raise_for_status=raise_for_status,
            validate_arguments=validate_arguments,
        )

    def __init_subclass__(cls, *, user_agent: str | None = None, **kwargs: Any) -> None:
        """Check the names in the class's body, set its default ``User-Agent``, and claim its endpoints.

        An endpoint or mounted resource can't use a name ``ClientX`` already uses, which
        includes all of ``httpx2.Client``'s, such as ``get`` or ``send``. Those names are
        free on a ``Resource``.

        Args:
            user_agent: The ``User-Agent`` this client sends unless the caller gives one.
                Defaults to the parent class's, ``ClientX/<version>`` for a direct subclass.
            **kwargs: Forwarded to ``object.__init_subclass__``.
        """
        super().__init_subclass__(**kwargs)
        set_up_client(cls, base=ClientX, user_agent=user_agent)


class AsyncClientX(_BaseClientX, AsyncClient):
    # Which kind of class this is: `async def` endpoints and resources. `_class_setup` reads it.
    __clientx_is_async__: ClassVar[bool] = True

    def __init__(
        self,
        base_url: URL | str,
        *,
        user_agent: str | None = None,
        raise_for_status: bool | None = None,
        validate_arguments: bool | None = None,
        **kwargs: Unpack[AsyncHttpxClientOptions],
    ) -> None:
        """Initialize a client with a base URL and optional ``httpx2.AsyncClient`` configuration.

        Takes the same arguments as ``ClientX``, except that ``transport`` and ``mounts``
        take async transports, and event hooks must be ``async`` functions.
        """
        super().__init__(base_url=base_url, **kwargs)
        _configure(
            self,
            user_agent=user_agent,
            headers=kwargs.get("headers"),
            raise_for_status=raise_for_status,
            validate_arguments=validate_arguments,
        )

    def __init_subclass__(cls, *, user_agent: str | None = None, **kwargs: Any) -> None:
        """Check the class's body, set its default ``User-Agent``, and claim its endpoints, as ``ClientX`` does."""
        super().__init_subclass__(**kwargs)
        set_up_client(cls, base=AsyncClientX, user_agent=user_agent)


def _configure(
    client: ClientX | AsyncClientX,
    *,
    user_agent: str | None,
    headers: HeaderTypes | None,
    raise_for_status: bool | None,
    validate_arguments: bool | None,
) -> None:
    """Set a new client's ``User-Agent``, and the settings the caller gave; ``None`` keeps the class's."""
    # httpx2 always sets its own User-Agent, so read the caller's from `headers=`, not from `client.headers`.
    client.headers["User-Agent"] = (
        user_agent or Headers(headers).get("User-Agent") or type(client).__clientx_user_agent__
    )
    if raise_for_status is not None:
        client.__clientx_raise_for_status__ = raise_for_status
    if validate_arguments is not None:
        client.__clientx_validate_arguments__ = validate_arguments


class _BaseResource:
    """What ``Resource`` and ``AsyncResource`` share: the prefix, the tags, and binding to a parent.

    Internal state uses ``__clientx_*__`` names, so names ``ClientX`` uses, such as
    ``close``, are free for endpoints on a resource.
    """

    __clientx_prefix__: ClassVar[str] = ""
    __clientx_tags__: ClassVar[tuple[str, ...]] = ()
    __clientx_parent__: ClientX | AsyncClientX | _BaseResource | None = None
    # Set by `Resource` and `AsyncResource`, as on the clients.
    __clientx_is_async__: ClassVar[bool]

    def __set_name__(self, owner: type[Any], name: str) -> None:
        """Check that the resource is mounted on a client or resource of its own kind."""
        check_mount(type(self).__qualname__, is_async=self.__clientx_is_async__, owner=owner)

    def __get__(self, instance: ClientX | AsyncClientX | _BaseResource | None, owner: type[Any] | None = None) -> Self:
        """Return a copy bound to ``instance``, or the resource itself on class access."""
        if instance is None:
            return self
        bound = copy(self)
        bound.__clientx_parent__ = instance
        return bound

    def __repr__(self) -> str:
        """Return the resource class name and its prefix."""
        return f"{type(self).__qualname__}(prefix={type(self).__clientx_prefix__!r})"


class Resource(_BaseResource):
    __clientx_is_async__: ClassVar[bool] = False

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
        set_up_resource(cls, base=Resource, prefix=prefix, tags=tags)


class AsyncResource(_BaseResource):
    __clientx_is_async__: ClassVar[bool] = True

    def __init_subclass__(cls, *, prefix: str | None = None, tags: Sequence[str] | None = None, **kwargs: Any) -> None:
        """Apply the class's prefix and tags to the endpoints defined in its body, as ``Resource`` does."""
        super().__init_subclass__(**kwargs)
        set_up_resource(cls, base=AsyncResource, prefix=prefix, tags=tags)


def client_of[C: ClientX | AsyncClientX](owner: object, kind: type[C]) -> C:
    """Return the client an endpoint call on ``owner`` goes through.

    Args:
        owner: The object the endpoint was called on: a client, or a resource mounted
            on one (possibly through other resources).
        kind: The client class the endpoint needs: ``ClientX`` for a ``def`` endpoint,
            ``AsyncClientX`` for an ``async def`` one.

    Raises:
        TypeError: If ``owner`` is a resource that isn't mounted on a client, or isn't
            a ``kind`` instance or a resource mounted on one.
    """
    current = owner
    while isinstance(current, _BaseResource):
        if current.__clientx_parent__ is None:
            name = type(current).__qualname__
            raise TypeError(
                f"Resource '{name}' isn't mounted on a client. Mount an instance as a class "
                f"attribute of a ClientX subclass (for example, `items = {name}()`) and call "
                "its endpoints through a client instance (`client.items.<endpoint>(...)`)."
            )
        current = current.__clientx_parent__
    if isinstance(current, kind):
        return current
    raise TypeError(
        f"The endpoint must be called on an instance of {kind.__name__} or a resource mounted on one, "
        f"not on {type(owner).__qualname__!r}."
    )
