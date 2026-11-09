from __future__ import annotations

from types import TracebackType
from typing import Any, ClassVar, Self, Unpack

from httpx2 import URL, Client, Response

from clientx._client_types import HttpxClientKwargs
from clientx._version import __version__


class ClientX:
    """Base HTTP client wrapper for declarative ClientX API clients.

    Attributes:
        client: Underlying ``httpx2.Client`` instance used to build and send requests.
    """

    _default_user_agent: ClassVar[str] = f"ClientX/{__version__}"
    _user_agent: str
    client: Client

    def __init__(
        self, base_url: URL | str, *, user_agent: str | None = None, **client_kwargs: Unpack[HttpxClientKwargs]
    ):
        """Initialize a client with a base URL and optional ``httpx2.Client`` configuration.

        Args:
            base_url: Base URL used for all relative request paths.
            user_agent: Optional user agent header value. When ``None``, uses the default ClientX user agent.
            **client_kwargs: Additional keyword arguments passed directly to ``httpx2.Client``.
        """
        self.client = Client(base_url=URL(base_url), **client_kwargs)
        self.user_agent = user_agent

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


__all__ = ["ClientX"]
