"""Serve a client's tools over MCP with FastMCP.

``fastmcp_tool(tool)`` turns a tool from ``clientx.tools.list_tools`` into a
FastMCP tool. Give the ones a model should use to your own ``FastMCP`` server,
with its ``tools=`` or ``add_tool()``, next to any tools of its own; the
server's name, transport and auth stay yours::

    from fastmcp import FastMCP

    tools = [fastmcp_tool(tool) for tool in list_tools(api) if tool.read_only]
    server = FastMCP("shop", tools=tools)
    server.run()

It needs FastMCP: ``pip install 'clientx[fastmcp]'``.
"""

from clientx._fastmcp import fastmcp_tool

__all__ = ["fastmcp_tool"]
