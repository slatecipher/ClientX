"""Pin the public import surface.

Anything listed here is a compatibility promise to users. Removing or renaming a
name should be a deliberate, changelogged decision, so it must fail a test first.
"""

import clientx
from clientx import decoders, exceptions, methods
from clientx.methods import get


def test_top_level_exports():
    assert sorted(clientx.__all__) == sorted(
        [
            "__version__",
            "Auth",
            "Request",
            "Response",
            "Timeout",
            "DumpConfig",
            "FieldX",
            "RequestPart",
            "ClientX",
            "Resource",
            "DeprecatedMessage",
            "Endpoint",
            "EndpointRegister",
            "URLPath",
            "ClientXError",
        ]
    )
    for name in clientx.__all__:
        assert hasattr(clientx, name), name


def test_submodule_exports():
    assert methods.__all__ == ["delete", "get", "head", "options", "patch", "post", "put"]
    assert sorted(decoders.__all__) == [
        "FromResponseDecoder",
        "ModelDecoder",
        "StreamChunksDecoder",
        "StreamDecoder",
        "StreamLinesDecoder",
        "StreamResponseDecoder",
        "TypeAdapterDecoder",
        "content_decoder",
        "json_decoder",
        "text_decoder",
    ]
    assert sorted(exceptions.__all__) == [
        "ClientXError",
        "EndpointNameConflictError",
        "MissingDecoderError",
        "MissingPathArgumentsError",
        "MissingReturnTypeError",
        "UnboundResourceError",
        "UnconsumableArgumentError",
    ]
    for module in (methods, decoders, exceptions):
        for name in module.__all__:
            assert hasattr(module, name), f"{module.__name__}.{name}"


def test_registry_yields_public_endpoint_types():
    class API(clientx.ClientX):
        @get("/v1/users/{user_id}")
        def get_user(self, user_id: str) -> clientx.Response: ...

    (endpoint,) = clientx.EndpointRegister.iter()

    assert isinstance(endpoint, clientx.Endpoint)
    assert isinstance(endpoint.path, clientx.URLPath)
    assert endpoint.path.parameters == ["user_id"]
