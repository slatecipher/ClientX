"""Turn ClientX tools into FastMCP tools, to serve them over MCP.

``fastmcp_tool(tool)`` returns a FastMCP tool, for ``FastMCP.add_tool``, that
calls a ``clientx.tools.Tool``:

- Schemas: its ``input_schema`` is the FastMCP tool's ``parameters``, as it
  is. FastMCP passes the model's arguments through unvalidated, so the ClientX
  tool validates them, leniently, and passes only those the model gave. MCP
  needs an output schema that describes an object, so a result that isn't
  one, such as a list, is wrapped as ``{"result": ...}``, marked as FastMCP
  marks its own, so FastMCP's client unwraps it.
- Hints and tags: ``read_only``, ``destructive`` and ``idempotent`` become
  MCP's ``readOnlyHint``, ``destructiveHint`` and ``idempotentHint``, and
  the tags become FastMCP's.
- Calls: an ``async def`` tool is awaited with ``acall()``. A ``def`` tool's
  ``call()`` runs in a worker thread, so it doesn't block the server. The
  result goes back as structured content, and as text: a string as it is,
  anything else as JSON.
- Errors: a ClientX ``ToolError`` becomes FastMCP's ``ToolError``, whose
  message the model sees. Any other exception becomes one that names only
  its type, as FastMCP would otherwise show its message, which can hold a
  URL or a credential. The original exception is the cause, for the server's
  logs.
"""

from __future__ import annotations

from typing import Any

import anyio.to_thread
from pydantic import PrivateAttr
from pydantic_core import to_json

from clientx.exceptions import ToolError
from clientx.tools import Tool

try:
    from fastmcp.exceptions import ToolError as FastMCPToolError
    from fastmcp.tools import Tool as FastMCPTool
    from fastmcp.tools import ToolResult
    from mcp_types import TextContent, ToolAnnotations
except ImportError as error:
    raise ImportError("clientx.fastmcp needs FastMCP: pip install 'clientx[fastmcp]'.") from error


def fastmcp_tool(tool: Tool) -> FastMCPTool:
    """Return a FastMCP tool that calls ``tool``, for ``FastMCP.add_tool``."""
    return _ClientXTool.calling(tool)


class _ClientXTool(FastMCPTool):
    """A FastMCP tool that calls a ClientX tool."""

    _tool: Tool = PrivateAttr()
    _wrapped: bool = PrivateAttr()  # The result goes in {"result": ...}.

    @classmethod
    def calling(cls, tool: Tool) -> _ClientXTool:
        """Return the FastMCP tool that calls ``tool``."""
        output_schema, wrapped = _output_schema(tool.output_schema)
        converted = cls(
            name=tool.name,
            description=tool.description,
            parameters=tool.input_schema,
            output_schema=output_schema,
            annotations=ToolAnnotations(
                read_only_hint=tool.read_only, destructive_hint=tool.destructive, idempotent_hint=tool.idempotent
            ),
            tags=set(tool.tags),
        )
        converted._tool = tool
        converted._wrapped = wrapped
        return converted

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Call the ClientX tool with the model's arguments.

        Raises:
            FastMCPToolError: If the call fails, with a message for the model.
        """
        try:
            if self._tool.is_async:
                result = await self._tool.acall(arguments)
            else:
                result = await anyio.to_thread.run_sync(self._tool.call, arguments)
        except ToolError as error:
            raise FastMCPToolError(str(error)) from error
        except Exception as error:  # noqa: BLE001 - its message can hold a URL or a credential.
            raise FastMCPToolError(f"{self._tool.name} failed unexpectedly ({type(error).__name__}).") from error
        if self._tool.output_schema is None:
            return ToolResult(content=[])
        text = result if isinstance(result, str) else to_json(result).decode()
        return ToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content={"result": result} if self._wrapped else result,
        )


def _output_schema(schema: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    """Return an output schema MCP accepts, and whether it wraps the result.

    MCP needs one that describes an object. Any other is wrapped as
    ``{"result": ...}``, with ``$defs`` kept at the top, where its references
    point, and marked ``x-fastmcp-wrap-result``, as FastMCP marks its own.
    """
    if schema is None or schema.get("type") == "object":
        return schema, False
    wrapper: dict[str, Any] = {
        "type": "object",
        "properties": {"result": {key: value for key, value in schema.items() if key != "$defs"}},
        "required": ["result"],
        "x-fastmcp-wrap-result": True,
    }
    if "$defs" in schema:
        wrapper["$defs"] = schema["$defs"]
    return wrapper, True
