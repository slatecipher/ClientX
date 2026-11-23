"""Serve a client's tools over MCP with FastMCP.

``fastmcp_tool(tool)`` turns a tool from ``clientx.tools.list_tools`` into a
FastMCP tool. Register the ones a model should use on your own ``FastMCP``
server, next to any tools of its own; the server's name, transport and auth
stay yours::

    from fastmcp import FastMCP

    server = FastMCP("shop")
    for tool in list_tools(api):
        if tool.read_only:
            server.add_tool(fastmcp_tool(tool))
    server.run()

It needs FastMCP: ``pip install 'clientx[fastmcp]'``.
"""

from clientx._fastmcp import fastmcp_tool

__all__ = ["fastmcp_tool"]
