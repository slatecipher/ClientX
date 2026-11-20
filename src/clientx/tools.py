"""Describe a client's endpoints as tools a model can call.

``list_tools(client)`` returns one ``Tool`` per endpoint a model can use, on
the client and the resources mounted on it. Each has a name, a description, a
JSON Schema of its arguments and of its result, hints from its HTTP method, and
``call()`` (or ``acall()`` for an async client), which validates a model's
arguments, calls the endpoint and returns JSON-ready data. A failed call raises
``ToolError``, with a message written for the model::

    for tool in list_tools(api):
        print(tool.name, tool.input_schema)

    tools = {tool.name: tool for tool in list_tools(api)}
    tools["users_search"].call({"name": "Ada"})

Nothing here depends on an AI library: register the tools with MCP or another
framework, which decides how a model sees and calls them.
"""

from clientx._tools import Tool, list_tools
from clientx.exceptions import ToolError

__all__ = ["Tool", "ToolError", "list_tools"]
