"""Pin the public import surface.

Anything listed here is a compatibility promise to users. Removing or renaming a
name should be a deliberate, changelogged decision, so it must fail a test first.
"""

import clientx
from clientx import decoders, exceptions, mcp, methods, tools


def test_top_level_exports():
    assert sorted(clientx.__all__) == sorted(
        [
            "__version__",
            "Auth",
            "Request",
            "Response",
            "Timeout",
            "Body",
            "DumpConfig",
            "File",
            "Form",
            "Header",
            "Query",
            "ClientX",
            "Resource",
            "DeprecatedMessage",
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
    assert sorted(tools.__all__) == ["Tool", "list_tools"]
    assert sorted(mcp.__all__) == ["create_mcp_server", "run_mcp_server"]
    for module in (methods, decoders, exceptions, tools, mcp):
        for name in module.__all__:
            assert hasattr(module, name), f"{module.__name__}.{name}"
