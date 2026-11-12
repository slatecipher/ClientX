"""Describe a client's endpoints as AI tools, and call them by name.

``list_tools(client)`` returns one ``Tool`` per endpoint on a client, including the
endpoints of mounted resources. Each tool has what AI tool-calling APIs and
protocols need: a name, a description, JSON Schemas for its arguments and result,
and hints derived from the HTTP method. ``Tool.call`` validates a model's arguments
against the schema and calls the endpoint through the client, so the client's
auth, decoders, and logging all apply.

This module has no dependencies beyond ClientX's own. ``clientx.mcp`` serves the
same tools over the Model Context Protocol.
"""

from __future__ import annotations

import inspect
import re
import warnings
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx2
from pydantic import BaseModel, ConfigDict, Field, PydanticUserError, TypeAdapter, create_model

from clientx._client import ClientX, Resource
from clientx._client_types import is_none_type, is_response_type
from clientx._endpoint_context import Endpoint
from clientx._registry import endpoint_for

_READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_DESTRUCTIVE_METHODS = frozenset({"PUT", "PATCH", "DELETE"})
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

# Valid for MCP, Anthropic, and OpenAI tool names alike.
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"status_code": {"type": "integer"}, "body": {}},
    "required": ["status_code", "body"],
}


@dataclass(frozen=True, kw_only=True)
class Tool:
    """One endpoint, described for AI tool calling.

    Attributes:
        name: Tool name: the endpoint's attribute path joined with underscores,
            such as ``"get_health"`` or ``"users_retrieve"`` for ``client.users.retrieve``.
        description: The endpoint's docstring, or ``"METHOD /path"`` without one.
        input_schema: JSON Schema (an object) for the arguments. Describe a
            parameter with its helper's ``description=``, such as
            ``Annotated[int, Query(description=...)]`` or ``PathParam(description=...)``
            for a path parameter, or with ``pydantic.Field(description=...)``.
        output_schema: JSON Schema for the result ``call`` returns, or ``None``
            when the endpoint returns nothing.
        method: HTTP method, such as ``"GET"``.
        path: Path template, such as ``"/users/{user_id}"``.
        tags: The endpoint's tags.
        read_only: The HTTP method doesn't change anything (GET, HEAD, OPTIONS).
        destructive: The method may change or delete existing data (PUT, PATCH, DELETE).
        idempotent: Repeating the call has no further effect (GET, HEAD, OPTIONS, PUT, DELETE).
        deprecated: The endpoint is deprecated.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    method: str
    path: str
    tags: tuple[str, ...]
    read_only: bool
    destructive: bool
    idempotent: bool
    deprecated: bool
    _function: Callable[..., Any] = field(repr=False, compare=False)
    _arguments: type[BaseModel] = field(repr=False, compare=False)
    _positional: tuple[str, ...] = field(repr=False, compare=False)
    _serialize: Callable[[Any], Any] = field(repr=False, compare=False)

    def call(self, arguments: Mapping[str, Any] | None = None) -> Any:
        """Validate ``arguments`` against ``input_schema`` and call the endpoint.

        Args:
            arguments: The arguments a model chose, keyed by parameter name.

        Returns:
            A JSON-friendly result matching ``output_schema``: the decoded value
            dumped in JSON mode, ``{"status_code": ..., "body": ...}`` for an
            endpoint that returns a ``Response``, or ``None``.

        Raises:
            pydantic.ValidationError: If the arguments don't match ``input_schema``.
        """
        validated = self._arguments.model_validate(dict(arguments or {}))
        values = {info.alias or name: getattr(validated, name) for name, info in type(validated).model_fields.items()}
        args = [values.pop(name) for name in self._positional]
        return self._serialize(self._function(*args, **values))


def list_tools(
    client: ClientX,
    *,
    read_only: bool = False,
    include_tags: Iterable[str] | None = None,
    exclude_tags: Iterable[str] = (),
    include_deprecated: bool = False,
) -> list[Tool]:
    """Describe a client's endpoints, including those on mounted resources, as tools.

    Streaming endpoints are left out: their results can't be returned as one value.
    An endpoint whose parameter or return types have no JSON Schema (such as file
    uploads) is left out with a warning.

    Args:
        client: The client whose endpoints become tools. Tools call through it.
        read_only: Only include endpoints whose HTTP method is read-only.
        include_tags: Only include endpoints with at least one of these tags.
        exclude_tags: Leave out endpoints with any of these tags.
        include_deprecated: Include deprecated endpoints, which are left out by default.

    Returns:
        The tools, in the order the endpoints are defined.

    Raises:
        ValueError: If a tool name is invalid or used twice.
    """
    included = None if include_tags is None else frozenset(include_tags)
    excluded = frozenset(exclude_tags)
    tools: dict[str, Tool] = {}

    for name, endpoint, function in _endpoints(client, ""):
        tags = frozenset(endpoint.tags)
        if (
            endpoint.stream
            or (endpoint.deprecated is not None and not include_deprecated)
            or (read_only and endpoint.method not in _READ_ONLY_METHODS)
            or (included is not None and not tags & included)
            or tags & excluded
        ):
            continue
        if not _TOOL_NAME.fullmatch(name):
            raise ValueError(
                f"Tool name {name!r} is invalid: tool names must be 1-64 characters from A-Z, a-z, 0-9, '_' and '-'. "
                "Shorten or rename the endpoint or the resource attribute."
            )
        if name in tools:
            raise ValueError(f"Two endpoints map to the tool name {name!r}; rename one of them.")
        tool = _build_tool(name, endpoint, function)
        if tool is not None:
            tools[name] = tool

    return list(tools.values())


def _endpoints(owner: ClientX | Resource, prefix: str) -> Iterator[tuple[str, Endpoint, Callable[..., Any]]]:
    """Yield ``(tool name, endpoint, bound function)`` for each endpoint on ``owner``, recursing into resources."""
    members: dict[str, object] = {}
    for cls in reversed(type(owner).__mro__):
        members.update(vars(cls))

    for name, value in members.items():
        endpoint = endpoint_for(value)
        if endpoint is not None:
            yield prefix + name, endpoint, getattr(owner, name)
        elif isinstance(value, Resource):
            yield from _endpoints(getattr(owner, name), f"{prefix}{name}_")


def _build_tool(name: str, endpoint: Endpoint, function: Callable[..., Any]) -> Tool | None:
    """Build the tool for one endpoint, or warn and return ``None`` if its types have no JSON Schema."""
    try:
        arguments, positional = _arguments_model(name, endpoint)
        input_schema = arguments.model_json_schema()
        output_schema, serialize = _output(endpoint)
    except PydanticUserError as error:
        warnings.warn(
            f"list_tools() left out endpoint {endpoint.func.__qualname__!r}: its types have no JSON Schema ({error})",
            stacklevel=3,
        )
        return None

    return Tool(
        name=name,
        description=inspect.getdoc(endpoint.func) or f"{endpoint.method} {endpoint.path}",
        input_schema=input_schema,
        output_schema=output_schema,
        method=endpoint.method,
        path=str(endpoint.path),
        tags=tuple(endpoint.tags),
        read_only=endpoint.method in _READ_ONLY_METHODS,
        destructive=endpoint.method in _DESTRUCTIVE_METHODS,
        idempotent=endpoint.method in _IDEMPOTENT_METHODS,
        deprecated=endpoint.deprecated is not None,
        _function=function,
        _arguments=arguments,
        _positional=positional,
        _serialize=serialize,
    )


def _arguments_model(name: str, endpoint: Endpoint) -> tuple[type[BaseModel], tuple[str, ...]]:
    """Build a model of the endpoint's parameters (after ``self``), and list the positional-only ones.

    Fields get internal names and the parameter name as their alias, so a
    parameter such as ``json`` can't clash with ``BaseModel``'s own attributes.
    """
    fields: dict[str, Any] = {}
    positional: list[str] = []
    parameters = list(endpoint.signature.parameters.values())[1:]

    for index, parameter in enumerate(parameters):
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            positional.append(parameter.name)
        default = ... if parameter.default is inspect.Parameter.empty else parameter.default
        # The endpoint's signature already has its annotations resolved, Annotated metadata included.
        annotation = Any if parameter.annotation is inspect.Parameter.empty else parameter.annotation
        fields[f"arg{index}"] = (annotation, Field(default, alias=parameter.name))

    model = create_model(name, __config__=ConfigDict(extra="forbid"), **fields)
    return model, tuple(positional)


def _output(endpoint: Endpoint) -> tuple[dict[str, Any] | None, Callable[[Any], Any]]:
    """Return the result's JSON Schema and a function that makes results JSON-friendly."""
    return_type = endpoint.return_type
    if is_none_type(return_type):
        return None, _no_result
    if is_response_type(return_type):
        return _RESPONSE_SCHEMA, _response_result
    adapter: TypeAdapter[Any] = TypeAdapter(return_type)
    # JSON Schema uses field aliases by default, so dump with them too: results must match the schema.
    return adapter.json_schema(mode="serialization"), lambda value: adapter.dump_python(
        value, mode="json", by_alias=True
    )


def _no_result(value: object) -> None:
    """Results of endpoints that return nothing."""


def _response_result(response: httpx2.Response) -> dict[str, Any]:
    """Describe a raw response as its status code and body: parsed JSON, or text."""
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return {"status_code": response.status_code, "body": body}


__all__ = ["Tool", "list_tools"]
