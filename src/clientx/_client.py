from __future__ import annotations

import logging
from types import TracebackType
from typing import Any, ClassVar, Self, Unpack

from httpx2 import URL, Client, Response

from clientx._client_types import HttpxClientKwargs
from clientx._version import __version__

logger = logging.getLogger(__name__)


def _log_request_parts(method: str, path: URL | str, stream: bool, request_parts: dict[str, Any]) -> None:
    """Log the raw request parts for a single request at debug level.

    Args:
        method: HTTP method name, such as ``"GET"`` or ``"POST"``.
        path: Request URL path or URL object the request targets.
        stream: Whether the response body will be streamed.
        request_parts: Request options as passed to ``httpx2.Client.build_request``.
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return
    part_types: dict[str, type[Any]] = {k: type(v) for k, v in request_parts.items()}
    logger.debug(
        "HTTP request parts: %s",
        {
            "method": method,
            "path": str(path),
            "stream": stream,
            "parts": part_types,
        },
    )


class ClientX:
    """Base HTTP client wrapper for declarative ClientX API clients.

    Attributes:
        client: Underlying ``httpx2.Client`` instance used to build and send requests.
    """

    _default_user_agent: ClassVar[str] = f"ClientX/{__version__}"
    _user_agent: str

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

    def send(self, method: str, path: URL | str, *, stream: bool = False, **request_parts: Any) -> Response:
        """Build and send a single HTTP request via the underlying ``httpx2.Client``.

        Args:
            method: HTTP method name, such as ``"GET"`` or ``"POST"``.
            path: Request URL path or URL object relative to ``base_url`` when applicable.
            stream: Whether to stream the response body instead of eagerly reading it.
            **request_parts: Additional request options forwarded to ``httpx2.Client.build_request``.

        Returns:
            The HTTP response returned by ``httpx2.Client.send``.
        """
        _log_request_parts(method, path, stream, request_parts)
        request = self.client.build_request(method=method, url=path, **request_parts)
        return self.client.send(request, stream=stream)


__all__ = ["ClientX"]
