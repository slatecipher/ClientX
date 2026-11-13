"""Serve a ClientX client as an MCP server.

Requires the ``mcp`` extra: ``pip install "clientx[mcp]"``.

Each tool from ``clientx.tools.list_tools`` becomes an MCP tool with the same name,
description, and JSON Schemas, and the HTTP-method hints become MCP tool
annotations. Only read-only endpoints (GET, HEAD, OPTIONS) are served unless
``read_only=False`` is passed. Tool calls run through the client, so its auth,
decoders, and logging apply, and errors come back to the MCP client as error results
instead of stopping the server::

    from clientx.mcp import run_mcp_server

    run_mcp_server(ExampleAPI("https://api.example.com"))

The client can be a ``ClientX`` or an ``AsyncClientX``. An async client's tools are
awaited on the server's event loop; a sync client's run in a worker thread, so they
don't block it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import httpx2

try:
    import anyio
    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
except ImportError as error:
    raise ImportError('clientx.mcp requires the "mcp" extra: pip install "clientx[mcp]"') from error

from clientx._client import AsyncClientX, ClientX
from clientx.tools import Tool, list_tools

# How much of an error response's body an error result includes: enough for the model to see what went wrong.
_ERROR_BODY_LIMIT = 1000


def create_mcp_server(
    client: ClientX | AsyncClientX,
    *,
    name: str | None = None,
    instructions: str | None = None,
    read_only: bool = True,
    include_tags: Iterable[str] | None = None,
    exclude_tags: Iterable[str] = (),
    include_deprecated: bool = False,
) -> Server[Any]:
    """Create an MCP server whose tools are the client's endpoints.

    The tool filters work as in ``clientx.tools.list_tools``, except that ``read_only``
    defaults to ``True``: a server exposes endpoints that change data only when asked to.
    To serve over stdio, use ``run_mcp_server``; for other transports, run the returned
    low-level ``mcp.server.lowlevel.Server`` yourself.

    Args:
        client: The client whose endpoints become tools. Tools call through it.
        name: Server name reported to MCP clients. Defaults to the client's class name.
        instructions: Optional instructions that MCP clients may show to the model.
        read_only: Only include endpoints whose HTTP method is read-only (GET, HEAD,
            OPTIONS). Pass ``False`` to serve POST, PUT, PATCH, and DELETE endpoints too.
        include_tags: Only include endpoints with at least one of these tags.
        exclude_tags: Leave out endpoints with any of these tags.
        include_deprecated: Include deprecated endpoints, which are left out by default.

    Returns:
        The MCP server.
    """
    tools = {
        tool.name: tool
        for tool in list_tools(
            client,
            read_only=read_only,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            include_deprecated=include_deprecated,
        )
    }
    definitions = [_definition(tool) for tool in tools.values()]

    async def on_list_tools(context: object, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
        return types.ListToolsResult(tools=definitions)

    async def on_call_tool(context: object, params: types.CallToolRequestParams) -> types.CallToolResult:
        tool = tools.get(params.name)
        if tool is None:
            return _error_result(f"Unknown tool: {params.name}")
        try:
            arguments = params.arguments or {}
            if tool.is_async:
                result = await tool.acall(arguments)
            else:  # A `def` endpoint blocks, so it runs off the event loop.
                result = await anyio.to_thread.run_sync(tool.call, arguments)
        except Exception as error:  # noqa: BLE001 - every failure must reach the MCP client as an error result
            return _error_result(_describe_error(error))
        return _success_result(tool, result)

    return Server(
        name or type(client).__name__,
        instructions=instructions,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


def run_mcp_server(
    client: ClientX | AsyncClientX,
    *,
    name: str | None = None,
    instructions: str | None = None,
    read_only: bool = True,
    include_tags: Iterable[str] | None = None,
    exclude_tags: Iterable[str] = (),
    include_deprecated: bool = False,
) -> None:
    """Serve the client's endpoints as MCP tools over stdio until the MCP client disconnects.

    MCP messages use stdout, so the server process must not print to it; use
    logging, which writes to stderr by default. The arguments are the same as for
    ``create_mcp_server``: only read-only endpoints are served unless ``read_only=False``.
    """
    server = create_mcp_server(
        client,
        name=name,
        instructions=instructions,
        read_only=read_only,
        include_tags=include_tags,
        exclude_tags=exclude_tags,
        include_deprecated=include_deprecated,
    )
    anyio.run(_serve_stdio, server)


async def _serve_stdio(server: Server[Any]) -> None:
    """Run ``server`` on this process's stdin and stdout."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def _definition(tool: Tool) -> types.Tool:
    """Describe a ClientX tool as an MCP tool."""
    return types.Tool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=_object_schema(tool.output_schema),
        annotations=types.ToolAnnotations(
            read_only_hint=tool.read_only,
            destructive_hint=tool.destructive,
            idempotent_hint=tool.idempotent,
            open_world_hint=True,
        ),
    )


def _object_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return an output schema MCP accepts: an object, wrapping other results in ``{"result": ...}``.

    ``$defs`` move to the top level so that ``#/$defs/...`` references still resolve.
    """
    if schema is None or schema.get("type") == "object":
        return schema
    inner = dict(schema)
    wrapped: dict[str, Any] = {"type": "object", "properties": {"result": inner}, "required": ["result"]}
    if "$defs" in inner:
        wrapped["$defs"] = inner.pop("$defs")
    return wrapped


def _success_result(tool: Tool, result: Any) -> types.CallToolResult:
    """Return the result as structured content and as JSON text."""
    text = types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
    if tool.output_schema is None:
        return types.CallToolResult(content=[text])
    structured = result if tool.output_schema.get("type") == "object" else {"result": result}
    return types.CallToolResult(content=[text], structured_content=structured)


def _describe_error(error: Exception) -> str:
    """Describe a failed tool call for the model.

    httpx2's ``HTTPStatusError`` message contains the request's full URL, so a query
    parameter such as an API key set with ``ClientX(params=...)`` would reach the model.
    A status error is described from its parts instead: the status, the method and path
    (no host or query string), and the start of the response body, which usually says what
    was wrong. Other errors don't include the URL and are described by their message.
    """
    if not isinstance(error, httpx2.HTTPStatusError):
        return f"{type(error).__name__}: {error}"
    response = error.response
    status = f"{response.status_code} {response.reason_phrase}".strip()
    message = f"HTTPStatusError: {status} for {error.request.method} {error.request.url.path}"
    # ClientX reads the body before raising, and tools never stream, so `text` is available.
    if body := response.text.strip():
        excerpt = body[:_ERROR_BODY_LIMIT] + ("…" if len(body) > _ERROR_BODY_LIMIT else "")
        message += f"\nResponse body: {excerpt}"
    return message


def _error_result(message: str) -> types.CallToolResult:
    """Return a tool error that the MCP client can show to the model."""
    return types.CallToolResult(content=[types.TextContent(type="text", text=message)], is_error=True)


__all__ = ["create_mcp_server", "run_mcp_server"]
