"""Serve a client's tools over MCP with FastMCP.

``fastmcp_tool(tool)`` turns a ClientX tool into a FastMCP tool, for your own
FastMCP server::

    from fastmcp import FastMCP

    tools = [fastmcp_tool(tool) for tool in list_tools(api) if tool.read_only]
    server = FastMCP("shop", tools=tools)
    server.run()

It needs FastMCP: ``pip install 'clientx[fastmcp]'``.
"""

from clientx._fastmcp import fastmcp_tool

__all__ = ["fastmcp_tool"]
