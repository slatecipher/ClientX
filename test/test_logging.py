import logging
import re
from collections.abc import Callable, Iterator
from typing import Annotated

import httpx2
import pytest

from clientx import ClientX, Header, Query, Response
from clientx.decoders import StreamLinesDecoder
from clientx.methods import get, post

FIELDS = (
    "clientx_endpoint",
    "clientx_method",
    "clientx_path",
    "clientx_parts",
    "clientx_stream",
    "clientx_status",
    "clientx_elapsed_ms",
    "clientx_error",
)


class UsersClient(ClientX):
    @post("/users/{user_id}")
    def update_user(
        self,
        user_id: int,
        json: dict[str, str],
        token: Annotated[str, Header("Authorization")],
        api_key: Annotated[str, Query()],
    ) -> Response: ...

    @get("/events", decoder=StreamLinesDecoder())
    def events(self) -> Iterator[str]: ...

    @get("/slow", timeout=5.0)
    def slow(self) -> None: ...


def make_client(handler: Callable[[httpx2.Request], httpx2.Response]) -> UsersClient:
    return UsersClient("https://api.example.com", transport=httpx2.MockTransport(handler))


def clientx_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "clientx"]


def logged_fields(record: logging.LogRecord) -> dict[str, object]:
    """Return the record's clientx_* fields, checking that the elapsed time is a non-negative float."""
    fields = {name: record.__dict__[name] for name in FIELDS}
    elapsed = fields.pop("clientx_elapsed_ms")
    assert isinstance(elapsed, float)
    assert elapsed >= 0
    return fields


def test_endpoint_call_logs_one_structured_debug_record(caplog):
    caplog.set_level(logging.DEBUG, logger="clientx")
    client = make_client(lambda request: httpx2.Response(201))

    client.update_user(42, {"name": "Ada"}, "Bearer token", "key")

    [record] = clientx_records(caplog)
    assert record.levelno == logging.DEBUG
    assert re.fullmatch(
        r"ClientX request: POST /users/42 -> 201 in \d+\.\d ms \(UsersClient\.update_user\)",
        record.getMessage(),
    )
    assert logged_fields(record) == {
        "clientx_endpoint": "UsersClient.update_user",
        "clientx_method": "POST",
        "clientx_path": "/users/42",
        "clientx_parts": ["headers", "json", "params"],
        "clientx_stream": False,
        "clientx_status": 201,
        "clientx_error": None,
    }


def test_logged_record_never_contains_values(caplog):
    caplog.set_level(logging.DEBUG, logger="clientx")
    client = make_client(lambda request: httpx2.Response(200))

    client.update_user(42, {"password": "hunter2"}, "Bearer SECRET-TOKEN", "KEY-123")

    [record] = clientx_records(caplog)
    logged = record.getMessage() + repr([record.__dict__[name] for name in FIELDS])
    for secret in ("hunter2", "SECRET-TOKEN", "KEY-123", "password", "api_key", "Authorization"):
        assert secret not in logged


def test_failed_call_logs_the_error_and_reraises(caplog):
    caplog.set_level(logging.DEBUG, logger="clientx")

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(httpx2.ConnectError):
        make_client(refuse).update_user(42, {}, "Bearer token", "key")

    [record] = clientx_records(caplog)
    assert re.fullmatch(
        r"ClientX request: POST /users/42 -> ConnectError in \d+\.\d ms \(UsersClient\.update_user\)",
        record.getMessage(),
    )
    fields = logged_fields(record)
    assert fields["clientx_status"] is None
    assert fields["clientx_error"] == "ConnectError"


def test_streamed_call_logs_stream_true(caplog):
    caplog.set_level(logging.DEBUG, logger="clientx")
    client = make_client(lambda request: httpx2.Response(200, text="a\nb"))

    assert list(client.events()) == ["a", "b"]

    [record] = clientx_records(caplog)
    fields = logged_fields(record)
    assert fields["clientx_stream"] is True
    assert fields["clientx_status"] == 200
    assert fields["clientx_parts"] == []


def test_timeout_option_is_not_logged_as_a_request_part(caplog):
    caplog.set_level(logging.DEBUG, logger="clientx")

    make_client(lambda request: httpx2.Response(204)).slow()

    [record] = clientx_records(caplog)
    assert logged_fields(record)["clientx_parts"] == []


def test_nothing_is_logged_when_debug_is_off(caplog):
    caplog.set_level(logging.INFO, logger="clientx")

    make_client(lambda request: httpx2.Response(200)).update_user(42, {}, "Bearer token", "key")

    assert clientx_records(caplog) == []
