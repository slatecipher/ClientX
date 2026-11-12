import inspect

import httpx2
import pytest
from httpx2 import Request, Response
from pydantic import BaseModel

from clientx._client import ClientX, send_request
from clientx._client_types import DumpConfig, HttpxClientKwargs
from clientx._version import __version__


def test_clientx_sets_default_user_agent():
    client = ClientX("https://example.test")

    assert client.user_agent == f"ClientX/{__version__}"
    assert client.client.headers["User-Agent"] == f"ClientX/{__version__}"


def test_clientx_uses_custom_user_agent():
    client = ClientX("https://example.test", user_agent="MyApp/1.0")

    assert client.user_agent == "MyApp/1.0"
    assert client.client.headers["User-Agent"] == "MyApp/1.0"


@pytest.mark.parametrize("name", ["User-Agent", "user-agent"])
def test_clientx_keeps_a_user_agent_given_in_headers(name: str):
    client = ClientX("https://example.test", headers={name: "MyApp/2.0", "X-Env": "dev"})

    assert client.user_agent == "MyApp/2.0"
    assert client.client.headers["User-Agent"] == "MyApp/2.0"
    assert client.client.headers["X-Env"] == "dev"


def test_clientx_user_agent_argument_wins_over_headers():
    client = ClientX("https://example.test", user_agent="Explicit/1.0", headers={"User-Agent": "FromHeaders/1.0"})

    assert client.user_agent == "Explicit/1.0"
    assert client.client.headers["User-Agent"] == "Explicit/1.0"


def test_clientx_user_agent_setter_updates_headers():
    client = ClientX("https://example.test")

    client.user_agent = "AnotherApp/2.0"

    assert client.user_agent == "AnotherApp/2.0"
    assert client.client.headers["User-Agent"] == "AnotherApp/2.0"


@pytest.mark.parametrize(("options", "streamed"), [({}, False), ({"stream": True}, True)], ids=["default", "stream"])
def test_send_request_builds_and_sends_request(monkeypatch, options: dict[str, bool], streamed: bool):
    client = ClientX("https://example.test")
    call_log: dict[str, object] = {}

    def fake_build_request(method: str, url: str, **request):
        call_log.update(method=method, url=url, request=request)
        return Request(method, f"https://example.test{url}")

    def fake_send(request: Request, *, stream: bool = False) -> Response:
        call_log["stream"] = stream
        return Response(status_code=204, request=request)

    monkeypatch.setattr(client.client, "build_request", fake_build_request)
    monkeypatch.setattr(client.client, "send", fake_send)

    response = send_request(client, "DELETE", "/v1/items/123", params={"dry_run": 1}, **options)

    assert response.status_code == 204
    assert call_log == {
        "method": "DELETE",
        "url": "/v1/items/123",
        "request": {"params": {"dry_run": 1}},
        "stream": streamed,
    }


def test_clientx_repr_includes_base_url_and_user_agent():
    client = ClientX("https://example.test", user_agent="MyApp/1.0")

    rendered = repr(client)

    assert rendered == "ClientX(base_url='https://example.test', user_agent='MyApp/1.0')"


def test_clientx_enter_delegates_to_httpx2_client(monkeypatch):
    client = ClientX("https://example.test")
    calls = {"entered": False}

    def fake_enter():
        calls["entered"] = True
        return object()

    monkeypatch.setattr(client.client, "__enter__", fake_enter)

    entered = client.__enter__()

    assert calls["entered"] is True
    assert entered is client


def test_clientx_exit_delegates_to_httpx2_client_and_never_swallows_an_error(monkeypatch):
    client = ClientX("https://example.test")
    calls: dict[str, object] = {}

    def fake_exit(exc_type, exc, tb):
        calls.update(exc_type=exc_type, exc=exc)
        return True  # Even if httpx2 asked to swallow the error, ClientX lets it propagate.

    monkeypatch.setattr(client.client, "__exit__", fake_exit)
    error = RuntimeError("boom")

    with pytest.raises(RuntimeError) as raised, client:
        raise error

    assert raised.value is error
    assert calls == {"exc_type": RuntimeError, "exc": error}


def test_httpx_client_kwargs_match_httpx2_client_signature():
    """HttpxClientKwargs is a hand-written mirror of httpx2.Client's options; catch drift.

    If httpx2 adds an option, add it to HttpxClientKwargs. If this fails under the
    lowest-versions CI job, an option we list is newer than our httpx2 lower bound.
    """
    parameters = inspect.signature(httpx2.Client.__init__).parameters
    client_options = {name for name, p in parameters.items() if name != "self" and p.kind is not p.VAR_KEYWORD}
    client_options -= {"base_url"}  # ClientX takes base_url as its own positional argument

    assert HttpxClientKwargs.__required_keys__ == frozenset()
    assert set(HttpxClientKwargs.__optional_keys__) == client_options


def test_dump_config_typed_dict_returns_fields():
    options = DumpConfig(exclude_none=True, exclude_defaults=True)

    assert options == {
        "exclude_none": True,
        "exclude_defaults": True,
    }


def test_dump_config_keys_are_model_dump_options():
    """DumpConfig is a chosen subset of model_dump's options, not a full copy, so it needn't track new ones.

    Every key must still be a model_dump parameter. If this fails under the lowest-versions
    CI job, an option we list is newer than our pydantic lower bound.
    """
    dump_options = set(inspect.signature(BaseModel.model_dump).parameters) - {"self"}

    assert DumpConfig.__required_keys__ == frozenset()
    assert DumpConfig.__optional_keys__ - dump_options == set()
