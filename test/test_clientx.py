import logging

from httpx import Request, Response

from clientx.__version__ import __version__
from clientx._client import ClientX


def test_clientx_sets_default_user_agent():
    client = ClientX("https://example.test")

    assert client.user_agent == f"ClientX/{__version__}"
    assert client.client.headers["User-Agent"] == f"ClientX/{__version__}"


def test_clientx_uses_custom_user_agent():
    client = ClientX("https://example.test", user_agent="MyApp/1.0")

    assert client.user_agent == "MyApp/1.0"
    assert client.client.headers["User-Agent"] == "MyApp/1.0"


def test_clientx_user_agent_setter_updates_headers():
    client = ClientX("https://example.test")

    client.user_agent = "AnotherApp/2.0"

    assert client.user_agent == "AnotherApp/2.0"
    assert client.client.headers["User-Agent"] == "AnotherApp/2.0"


def test_clientx_send_builds_and_sends_request(monkeypatch):
    client = ClientX("https://example.test")
    call_log: dict[str, object] = {}

    def fake_build_request(method: str, url: str, **request):
        call_log["method"] = method
        call_log["url"] = url
        call_log["request"] = request
        return Request(method, f"https://example.test{url}")

    def fake_send(request: Request) -> Response:
        call_log["built_request"] = request
        return Response(status_code=204, request=request)

    monkeypatch.setattr(client.client, "build_request", fake_build_request)
    monkeypatch.setattr(client.client, "send", fake_send)

    response = client.send("DELETE", "/v1/items/123", params={"dry_run": 1})

    assert response.status_code == 204
    assert call_log["method"] == "DELETE"
    assert call_log["url"] == "/v1/items/123"
    assert call_log["request"] == {"params": {"dry_run": 1}}


def test_clientx_send_logs_request_parts_when_debug_enabled(monkeypatch, caplog):
    client = ClientX("https://example.test")

    def fake_build_request(method: str, url: str, **request):
        return Request(method, f"https://example.test{url}")

    def fake_send(request: Request) -> Response:
        return Response(status_code=200, request=request)

    monkeypatch.setattr(client.client, "build_request", fake_build_request)
    monkeypatch.setattr(client.client, "send", fake_send)
    caplog.set_level(logging.DEBUG, logger="clientx._client")

    client.send("POST", "/v1/items", json={"id": 1}, headers={"x-token": "abc"})

    assert "HTTP request parts" in caplog.text
    assert "method" in caplog.text
    assert "path" in caplog.text


def test_clientx_repr_includes_base_url_and_user_agent():
    client = ClientX("https://example.test", user_agent="MyApp/1.0")

    rendered = repr(client)

    assert rendered == "ClientX(base_url='https://example.test', user_agent='MyApp/1.0')"


def test_clientx_enter_delegates_to_httpx_client(monkeypatch):
    client = ClientX("https://example.test")
    calls = {"entered": False}

    def fake_enter():
        calls["entered"] = True
        return object()

    monkeypatch.setattr(client.client, "__enter__", fake_enter)

    entered = client.__enter__()

    assert calls["entered"] is True
    assert entered is client


def test_clientx_exit_delegates_to_httpx_client_and_returns_false(monkeypatch):
    client = ClientX("https://example.test")
    calls: dict[str, object] = {}

    def fake_exit(exc_type, exc, tb):
        calls["exc_type"] = exc_type
        calls["exc"] = exc
        calls["tb"] = tb
        return True

    monkeypatch.setattr(client.client, "__exit__", fake_exit)
    error = RuntimeError("boom")

    result = client.__exit__(RuntimeError, error, None)

    assert result is False
    assert calls["exc_type"] is RuntimeError
    assert calls["exc"] is error
    assert calls["tb"] is None
