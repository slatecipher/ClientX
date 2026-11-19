"""The names ClientX exports. A change here is a change to the public API."""

import importlib.metadata
import re
from pathlib import Path

import clientx
from clientx import arguments, exceptions, method, tools


def test_package_exports() -> None:
    assert sorted(clientx.__all__) == sorted(
        [
            "__version__",
            "Auth",
            "Request",
            "Response",
            "Timeout",
            "AsyncClientX",
            "AsyncResource",
            "ClientX",
            "Resource",
            "Body",
            "File",
            "Form",
            "Header",
            "Json",
            "Query",
            "Send",
            "Url",
            "ArgumentError",
            "ClientXError",
            "DefinitionError",
            "method",
        ]
    )
    for name in clientx.__all__:
        assert hasattr(clientx, name), name


def test_submodule_exports() -> None:
    assert method.__all__ == ["delete", "get", "head", "options", "patch", "post", "put"]
    assert sorted(arguments.__all__) == ["Body", "File", "Form", "Header", "Json", "Query", "Send", "Url"]
    assert sorted(exceptions.__all__) == ["ArgumentError", "ClientXError", "DefinitionError", "ToolError"]
    assert sorted(tools.__all__) == ["Tool", "ToolError", "list_tools"]


def test_the_reference_page_lists_every_public_name() -> None:
    # The index table at the top of docs/reference.md names each public name in
    # backticks, so a name added or removed must be added or removed there too.
    page = (Path(__file__).parent.parent / "docs" / "reference.md").read_text()
    index = page[page.index("| Name | What it is |") :].split("\n\n", 1)[0]
    assert set(re.findall(r"`(\w+)`", index)) == {*clientx.__all__, *method.__all__, *tools.__all__}


def test_version_is_the_installed_one() -> None:
    assert clientx.__version__ == importlib.metadata.version("clientx")


def test_exceptions_keep_a_built_in_base() -> None:
    # So `except TypeError` and `except ValueError` handlers keep catching them.
    assert issubclass(exceptions.DefinitionError, exceptions.ClientXError)
    assert issubclass(exceptions.DefinitionError, TypeError)
    assert issubclass(exceptions.ArgumentError, exceptions.ClientXError)
    assert issubclass(exceptions.ArgumentError, ValueError)
    assert exceptions.ArgumentError("message", parameter="user_id").parameter == "user_id"
