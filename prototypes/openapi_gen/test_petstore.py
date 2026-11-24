"""Check the client generated from the Petstore spec against the wire.

Run with ``uv run pytest prototypes/openapi_gen --no-cov``.
"""

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx2
import pytest

HERE = Path(__file__).parent
PET = {"id": 7, "name": "doggie", "photoUrls": ["https://x/1.png"], "status": "available"}

type Handler = Callable[[httpx2.Request], httpx2.Response]


@pytest.fixture(scope="module")
def petstore() -> ModuleType:
    spec = importlib.util.spec_from_file_location("petstore", HERE / "petstore.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sent() -> list[httpx2.Request]:
    return []


@pytest.fixture
def client(petstore: ModuleType, sent: list[httpx2.Request]) -> Iterator[Any]:
    responses: dict[tuple[str, str], httpx2.Response] = {}

    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        key = (request.method, request.url.path)
        return responses.get(key) or httpx2.Response(200, json=PET)

    with petstore.PetstoreClient(transport=httpx2.MockTransport(answer)) as api:
        api.responses = responses
        yield api


def test_the_committed_client_is_what_the_generator_writes(tmp_path: Path) -> None:
    out = tmp_path / "petstore.py"
    (tmp_path / "ruff.toml").write_text(
        (HERE.parent / "ruff.toml").read_text().replace("../ruff.toml", str(HERE.parent.parent / "ruff.toml"))
    )
    subprocess.run(
        [sys.executable, HERE / "generate.py", HERE / "petstore3.yaml", "-o", out, "--class-name", "PetstoreClient"],
        check=True,
        capture_output=True,
    )
    assert out.read_text() == (HERE / "petstore.py").read_text()


def test_base_url_comes_from_servers(client: Any, sent: list[httpx2.Request]) -> None:
    client.pet.get_pet_by_id(7)

    assert str(sent[0].url) == "https://petstore3.swagger.io/api/v3/pet/7"


def test_a_json_body_is_sent_by_alias_and_the_response_decoded(
    petstore: ModuleType, client: Any, sent: list[httpx2.Request]
) -> None:
    pet = petstore.Pet(name="doggie", photo_urls=["https://x/1.png"])

    created = client.pet.add_pet(pet)

    assert sent[0].method == "POST"
    assert sent[0].url.path == "/api/v3/pet"
    assert json.loads(sent[0].content) == {
        "id": None,
        "name": "doggie",
        "category": None,
        "photoUrls": ["https://x/1.png"],
        "tags": None,
        "status": None,
    }
    assert created == petstore.Pet.model_validate(PET)


def test_query_parameters_use_the_spec_names(client: Any, sent: list[httpx2.Request]) -> None:
    client.responses["GET", "/api/v3/pet/findByTags"] = httpx2.Response(200, json=[PET])
    client.responses["GET", "/api/v3/pet/findByStatus"] = httpx2.Response(200, json=[PET])
    client.pet.upload_file(7, additional_metadata="front", body=b"\x89PNG")
    client.pet.find_pets_by_tags(["a", "b"])
    client.pet.find_pets_by_status()

    upload, by_tags, by_status = sent
    assert upload.url.path == "/api/v3/pet/7/uploadImage"
    assert upload.url.params["additionalMetadata"] == "front"
    assert upload.content == b"\x89PNG"
    assert by_tags.url.params.get_list("tags") == ["a", "b"]
    assert by_status.url.params["status"] == "available"


def test_a_header_parameter_keeps_its_spec_name(client: Any, sent: list[httpx2.Request]) -> None:
    client.pet.delete_pet(7, api_key="secret")

    assert sent[0].method == "DELETE"
    assert sent[0].headers["api_key"] == "secret"


def test_an_optional_header_left_out_is_not_sent(client: Any, sent: list[httpx2.Request]) -> None:
    client.pet.delete_pet(7)

    assert "api_key" not in sent[0].headers


def test_a_map_response_decodes(client: Any) -> None:
    client.responses["GET", "/api/v3/store/inventory"] = httpx2.Response(200, json={"available": 3})

    assert client.store.get_inventory() == {"available": 3}


def test_a_text_response_decodes_as_text(client: Any) -> None:
    client.responses["GET", "/api/v3/user/login"] = httpx2.Response(200, text="logged in user session:123")

    assert client.user.login_user(username="u", password="p") == "logged in user session:123"


def test_a_path_value_is_percent_encoded(client: Any, sent: list[httpx2.Request]) -> None:
    client.responses["GET", "/api/v3/user/a/b"] = httpx2.Response(200, json={})
    client.user.get_user_by_name("a/b")

    assert sent[0].url.raw_path == b"/api/v3/user/a%2Fb"


def test_the_api_key_auth_sets_its_header(petstore: ModuleType, sent: list[httpx2.Request]) -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json={})

    with petstore.PetstoreClient(transport=httpx2.MockTransport(answer), auth=petstore.ApiKeyAuth("k")) as api:
        api.store.get_inventory()

    assert sent[0].headers["api_key"] == "k"


def test_every_operation_is_a_tool(client: Any) -> None:
    from clientx.tools import list_tools  # noqa: PLC0415

    tools = {tool.name: tool for tool in list_tools(client)}

    assert len(tools) == 19
    assert tools["pet_get_pet_by_id"].tags[0] == "pet"
    status = tools["pet_find_pets_by_status"].input_schema["properties"]["status"]
    assert status["description"] == "Status values that need to be considered for filter"


def test_a_tool_call_sends_the_request(client: Any, sent: list[httpx2.Request]) -> None:
    from clientx.tools import list_tools  # noqa: PLC0415

    tools = {tool.name: tool for tool in list_tools(client)}
    order = {"id": 3, "petId": 7, "status": "placed"}
    client.responses["GET", "/api/v3/store/order/3"] = httpx2.Response(200, json=order)

    result = tools["store_get_order_by_id"].call({"order_id": 3})

    assert sent[0].url.path == "/api/v3/store/order/3"
    assert result["id"] == 3


@pytest.mark.xfail(
    strict=True,
    reason="ClientX bug: output_schema is by alias (petId), call() dumps by name (pet_id)",
)
def test_a_tool_result_uses_its_output_schemas_names(client: Any) -> None:
    from clientx.tools import list_tools  # noqa: PLC0415

    tool = next(tool for tool in list_tools(client) if tool.name == "store_get_order_by_id")
    client.responses["GET", "/api/v3/store/order/3"] = httpx2.Response(200, json={"id": 3, "petId": 7})

    result = tool.call({"order_id": 3})

    assert tool.output_schema is not None
    assert set(result) == set(tool.output_schema["properties"])
