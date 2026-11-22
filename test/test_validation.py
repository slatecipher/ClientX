"""Argument validation: a client created with ``validate_arguments=True``."""

import io
from collections.abc import Callable
from typing import Annotated, Any, BinaryIO

import httpx2
import pytest
from pydantic import BaseModel, ValidationError

from clientx import ArgumentError, AsyncClientX, ClientX, File, Form, Json, Query, method

type MockTransport = Callable[..., httpx2.MockTransport]

BASE_URL = "https://api.example.com"


class User(BaseModel):
    name: str


class API(ClientX):
    @method.get("/users")
    def users(self, page: Annotated[int, Query(ge=1)], size: Annotated[int, Query(le=100)] = 10) -> None: ...


def test_arguments_arent_checked_by_default(mock_transport: MockTransport) -> None:
    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).users(0)
    assert sent[0].url.params["page"] == "0"


def test_arguments_that_dont_fit_raise_before_sending(mock_transport: MockTransport) -> None:
    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent), validate_arguments=True)
    with pytest.raises(ArgumentError) as caught:
        api.users(0, size=500)
    assert caught.value.parameter == "page"
    assert "page: Input should be greater than or equal to 1 (got 0)" in str(caught.value)
    assert "size: Input should be less than or equal to 100 (got 500)" in str(caught.value)
    assert isinstance(caught.value.__cause__, ValidationError)
    assert sent == []


def test_checking_is_strict(mock_transport: MockTransport) -> None:
    api = API(BASE_URL, transport=mock_transport(), validate_arguments=True)
    with pytest.raises(ArgumentError, match="page: Input should be a valid integer"):
        api.users("7")  # pyright: ignore[reportArgumentType]


def test_defaults_arent_checked(mock_transport: MockTransport) -> None:
    class Search(ClientX):
        @method.get("/search")
        def search(self, page: Annotated[int, Query()] = None) -> None: ...  # pyright: ignore[reportArgumentType]

    sent: list[httpx2.Request] = []
    Search(BASE_URL, transport=mock_transport(sent), validate_arguments=True).search()
    assert "page" not in sent[0].url.params


def test_the_callers_values_are_sent_unchanged(mock_transport: MockTransport) -> None:
    class Users(ClientX):
        @method.post("/users")
        def create(self, user: Annotated[User, Json()], ratio: Annotated[float, Query()]) -> None: ...

    sent: list[httpx2.Request] = []
    Users(BASE_URL, transport=mock_transport(sent), validate_arguments=True).create(User(name="Ada"), 3)
    assert (sent[0].url.params["ratio"], sent[0].content) == ("3", b'{"name":"Ada"}')


def test_a_parameter_pydantic_cant_validate_isnt_checked(mock_transport: MockTransport) -> None:
    class Files(ClientX):
        @method.post("/files")
        def upload(self, doc: Annotated[BinaryIO, File()], copies: Annotated[int, Form(ge=1)]) -> None: ...

    sent: list[httpx2.Request] = []
    api = Files(BASE_URL, transport=mock_transport(sent), validate_arguments=True)
    api.upload(io.BytesIO(b"%PDF"), 1)
    with pytest.raises(ArgumentError, match="copies"):
        api.upload(io.BytesIO(b"%PDF"), 0)
    assert len(sent) == 1


@pytest.mark.anyio
async def test_async_clients_check_too(mock_transport: MockTransport) -> None:
    class AsyncAPI(AsyncClientX):
        @method.get("/users")
        async def users(self, page: Annotated[int, Query(ge=1)]) -> Any: ...

    api = AsyncAPI(BASE_URL, transport=mock_transport(), validate_arguments=True)
    with pytest.raises(ArgumentError, match="page"):
        await api.users(0)
