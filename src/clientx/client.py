from __future__ import annotations

from typing import ClassVar, Unpack

import httpx

from clientx import __version__
from clientx.client_types import HttpxClientKwargs


class ClientX:
    _default_user_agent: ClassVar[str] = f"ClientX/{__version__}"
    _user_agent: str

    def __init__(self, *, _httpx_client: httpx.Client, _user_agent: str | None = None):
        self._client = _httpx_client
        self.user_agent = _user_agent

    @property
    def user_agent(self) -> str:
        return self._user_agent

    @user_agent.setter
    def user_agent(self, value: str | None):
        self._user_agent = value or type(self)._default_user_agent
        self._client.headers.update({"User-Agent": self._user_agent})

    def send(self, method, path, **request) -> httpx.Response:
        request = self._client.build_request(method=method, url=path, **request)
        return self._client.send(request)

    @classmethod
    def setup_client(
        cls,
        base_url: str | httpx.URL,
        *,
        user_agent: str | None = None,
        **client_kwargs: Unpack[HttpxClientKwargs],
    ):
        return cls(
            _httpx_client=httpx.Client(base_url=base_url, **client_kwargs),
            _user_agent=user_agent,
        )
