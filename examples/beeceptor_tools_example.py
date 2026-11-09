"""Show the Beeceptor client's endpoints as AI tools.

Prints the tool list, one tool's definition and output schema, a filtered list,
and calls with valid and invalid arguments.
"""

import json

from beeceptor import Beeceptor
from pydantic import ValidationError

from clientx.tools import list_tools


def main() -> None:
    with Beeceptor("https://fake-json-api.mock.beeceptor.com") as client:
        # One tool per endpoint, including the endpoints on the client's resources.
        # Deprecated endpoints are left out unless you ask for them.
        tools = {tool.name: tool for tool in list_tools(client, include_deprecated=True)}

        print("Tools:")
        for tool in tools.values():
            hints = ", ".join(name for name in ("read_only", "destructive", "idempotent") if getattr(tool, name))
            deprecated = " (deprecated)" if tool.deprecated else ""
            print(f"  {tool.name}: {tool.method} {tool.path} [{hints}]{deprecated}")

        # What you'd pass to an AI SDK as a tool definition. The description is the
        # endpoint's docstring, and the input schema comes from its parameters.
        retrieve = tools["users_retrieve"]
        definition = {"name": retrieve.name, "description": retrieve.description, "input_schema": retrieve.input_schema}
        print("\nTool definition for users_retrieve:")
        print(json.dumps(definition, indent=2))

        # The output schema comes from the return type (here the User model).
        print("\nOutput schema for users_retrieve:")
        print(json.dumps(retrieve.output_schema, indent=2))

        # Filters choose what an agent can use.
        print(f"\nRead-only tools: {[tool.name for tool in list_tools(client, read_only=True)]}")

        # Models send JSON arguments. call() validates and converts them ("3" becomes 3),
        # then sends the request through the client and returns a JSON-friendly result.
        print("\nusers_retrieve.call({'user_id': '3'}):")
        print(json.dumps(retrieve.call({"user_id": "3"}), indent=2))

        # Invalid arguments raise ValidationError before any request is sent.
        try:
            retrieve.call({"user_id": "three"})
        except ValidationError as error:
            print(f"\nusers_retrieve.call({{'user_id': 'three'}}) raised ValidationError:\n{error}")


if __name__ == "__main__":
    main()
