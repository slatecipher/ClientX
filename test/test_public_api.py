"""The names ClientX exports. A change here is a change to the public API."""

import importlib.metadata

import clientx
from clientx import arguments, exceptions, method


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
    assert sorted(arguments.__all__) == ["Body", "File", "Form", "Header", "Json", "Query", "Url"]
    assert sorted(exceptions.__all__) == ["ArgumentError", "ClientXError", "DefinitionError"]


def test_version_is_the_installed_one() -> None:
    assert clientx.__version__ == importlib.metadata.version("clientx")


def test_exceptions_keep_a_built_in_base() -> None:
    # So `except TypeError` and `except ValueError` handlers keep catching them.
    assert issubclass(exceptions.DefinitionError, exceptions.ClientXError)
    assert issubclass(exceptions.DefinitionError, TypeError)
    assert issubclass(exceptions.ArgumentError, exceptions.ClientXError)
    assert issubclass(exceptions.ArgumentError, ValueError)
    assert exceptions.ArgumentError("message", parameter="user_id").parameter == "user_id"
