from __future__ import annotations

import logging
from typing import ClassVar, Unpack

from httpx import URL, Client, Response

from clientx.__version__ import __version__
from clientx._client_types import HttpxClientKwargs

logger = logging.getLogger(__name__)


class ClientX:
    _default_user_agent: ClassVar[str] = f"ClientX/{__version__}"
    _user_agent: str

    def __init__(
        self, base_url: URL | str, *, user_agent: str | None = None, **client_kwargs: Unpack[HttpxClientKwargs]
    ):
        self.client = Client(base_url=URL(base_url), **client_kwargs)
        self.user_agent = user_agent

    @property
    def user_agent(self) -> str:
        return self._user_agent

    @user_agent.setter
    def user_agent(self, value: str | None):
        self._user_agent = value or type(self)._default_user_agent
        self.client.headers.update({"User-Agent": self._user_agent})

    def send(self, method: str, path, **request) -> Response:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "HTTP request parts: %s",
                {
                    "method": method,
                    "path": str(path),
                    "parts": {k: type(v) for k, v in request.items()},
                },
            )
        request = self.client.build_request(method=method, url=path, **request)
        return self.client.send(request)


__all__ = ["ClientX"]
