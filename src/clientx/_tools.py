"""Describe a client's endpoints as tools a model can call.

``list_tools(client)`` returns one ``Tool`` per endpoint on the client and the
resources mounted on it: a name, a description, a JSON Schema of its arguments
and of its result, hints from its HTTP method, and ``call()`` or ``acall()``.
Nothing here depends on an AI library, so an adapter for MCP or another
framework can build on it.

- Names: the attribute path from the client, joined with ``_``, so
  ``api.users.create`` is ``users_create``. An endpoint's second name in its
  class is left out: it's the same endpoint.
- Left out: an endpoint that streams (``-> Iterator[...]`` or
  ``stream=True``), returns the raw ``Response``, or has an argument with no
  JSON form, such as a binary file. A model can't use them well.
- Descriptions: the docstring, up to its first section (``Args:``,
  ``Returns:``...), or else the method and path. An argument's description is
  its helper's ``description=``, or else its entry in the docstring's
  ``Args:``.
- Schemas: arguments are named as in the method, not by their helpers'
  aliases. Pydantic's ``title`` on each property is left out, and a model or
  ``type`` alias is written in place rather than behind a ``$ref``, unless it
  refers to itself.
- Calls: a model's arguments are validated as Pydantic validates a call,
  leniently, so ``"7"`` fits an ``int``. Only the arguments the model gave are
  passed, so a default stays a default, as ``Send(exclude_unset=True)`` and a
  JSON field's ``None`` need. The result is JSON-ready data.
- Errors: a failed call raises ``ToolError``, with a message written for a
  model and the original error as its cause. HTTP errors name the method and
  path template, never the host or query string, which can hold credentials.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import NoneType
from typing import TYPE_CHECKING, Any, cast

import httpx2
from pydantic import ConfigDict, PydanticSchemaGenerationError, TypeAdapter, ValidationError
from pydantic.errors import PydanticInvalidForJsonSchema

from clientx._registry import endpoint_for
from clientx.exceptions import ArgumentError, ToolError

if TYPE_CHECKING:
    from clientx._client import AsyncClientX, ClientX
    from clientx._endpoint import Endpoint
    from clientx._signature import ParameterInfo


# --- Entry point --------------------------------------------------------------
def list_tools(client: ClientX | AsyncClientX) -> list[Tool]:
    """Return a tool for each endpoint a model can call, resources' included.

    Every endpoint on the client and the resources mounted on it is a tool,
    named by its attribute path (``users_create``), except one a model can't
    use well:

    - one that streams, annotated ``-> Iterator[...]`` or with
      ``stream=True``;
    - one that returns the raw ``Response``: annotate what the API returns
      instead, such as a model or ``dict[str, Any]``;
    - one with an argument that has no JSON form, such as a binary file.

    An endpoint's second name in its class is listed once.
    """
    tools: list[Tool] = []
    _collect(client, "", tools, set())
    return tools


def _collect(owner: object, prefix: str, tools: list[Tool], seen: set[int]) -> None:
    """Add a tool for each endpoint on ``owner``, then on its resources.

    ``seen`` holds each endpoint met so far, by ``id``, so an endpoint's second
    name is left out.
    """
    for name, value in _members(type(owner)).items():
        endpoint = endpoint_for(value)
        if endpoint is not None and id(endpoint) not in seen:
            seen.add(id(endpoint))
            tool = _tool(prefix + name, endpoint, getattr(owner, name))
            if tool is not None:
                tools.append(tool)
        elif hasattr(type(value), "__clientx_prefix__"):  # A mounted resource.
            _collect(getattr(owner, name), f"{prefix}{name}_", tools, seen)


def _members(cls: type) -> dict[str, object]:
    """Return the attributes ``cls`` and its parents define, in class order."""
    members: dict[str, object] = {}
    for class_ in reversed(cls.__mro__):
        members.update(vars(class_))
    return members


# --- Tools --------------------------------------------------------------------
@dataclass(frozen=True, kw_only=True)
class Tool:
    """An endpoint described for a model, and called with a model's arguments.

    Attributes:
        name: The attribute path from the client, joined with ``_``.
        description: What the endpoint does, from its docstring.
        input_schema: The JSON Schema of the arguments: an object with one
            property per parameter, named as in the method.
        output_schema: The JSON Schema of the result, or ``None`` for an
            endpoint annotated ``-> None``.
        read_only: The endpoint only reads: ``GET``, ``HEAD`` or ``OPTIONS``.
        destructive: It can change or delete what's there: ``PUT``,
            ``PATCH`` or ``DELETE``.
        idempotent: Calling it twice has the effect of calling it once:
            ``GET``, ``HEAD``, ``OPTIONS``, ``PUT`` or ``DELETE``.
        is_async: It's an ``async def`` endpoint, called with ``acall()``.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    read_only: bool
    destructive: bool
    idempotent: bool
    is_async: bool
    _call: _Call = field(repr=False, compare=False)

    def call(self, arguments: Mapping[str, Any] | None = None) -> Any:
        """Call the endpoint with a model's arguments; return JSON-ready data.

        Raises:
            ToolError: If the arguments don't fit, the request can't be sent or
                fails, or the response doesn't fit the endpoint's annotation.
            TypeError: If the endpoint is ``async def``: use ``acall()``.
        """
        if self.is_async:
            raise TypeError(f"Tool {self.name!r} is an async def endpoint: call it with acall().")
        args, kwargs = self._call.arguments(self.name, arguments)
        with self._call.errors(self.name):
            result = self._call.function(*args, **kwargs)
        return self._call.dump(result)

    async def acall(self, arguments: Mapping[str, Any] | None = None) -> Any:
        """Call the ``async def`` endpoint with a model's arguments.

        Raises:
            ToolError: As for ``call()``.
            TypeError: If the endpoint is a plain ``def``: use ``call()``.
        """
        if not self.is_async:
            raise TypeError(f"Tool {self.name!r} is a def endpoint: call it with call().")
        args, kwargs = self._call.arguments(self.name, arguments)
        with self._call.errors(self.name):
            result = await self._call.function(*args, **kwargs)
        return self._call.dump(result)


@dataclass(frozen=True)
class _Call:
    """What a tool needs to call its endpoint and report on it."""

    function: Callable[..., Any]
    adapter: TypeAdapter[dict[str, Any]]
    output: TypeAdapter[Any] | None
    positional: tuple[ParameterInfo, ...]
    request: str  # The method and path template, for messages: "POST /users".

    def arguments(self, name: str, arguments: Mapping[str, Any] | None) -> tuple[list[Any], dict[str, Any]]:
        """Return the validated arguments the model gave, to call with.

        A positional-only parameter is passed by position, so one the model
        left out before one it gave gets its default.

        Raises:
            ToolError: If the arguments don't fit the endpoint's parameters.
        """
        given = dict(arguments or {})
        try:
            validated = self.adapter.validate_python(given)
        except ValidationError as error:
            raise ToolError(
                f"The arguments don't fit {name}: {_problems(error, values=True)}. Nothing was sent.", tool=name
            ) from error
        last = max((index for index, parameter in enumerate(self.positional) if parameter.name in given), default=-1)
        args = [validated.get(parameter.name, parameter.default) for parameter in self.positional[: last + 1]]
        positional_names = {parameter.name for parameter in self.positional}
        kwargs = {key: value for key, value in validated.items() if key in given and key not in positional_names}
        return args, kwargs

    @contextmanager
    def errors(self, name: str) -> Generator[None]:
        """Raise ``ToolError`` for what can go wrong in a call, with its cause.

        An HTTP error shows the API's own answer, truncated, as it often says
        what to fix.
        """
        try:
            yield
        except ArgumentError as error:
            raise ToolError(f"{name} couldn't send its request: {error}", tool=name) from error
        except httpx2.HTTPStatusError as error:
            response = error.response
            message = f"{name}: the API answered {response.status_code} {response.reason_phrase} to {self.request}"
            body = response.text.strip()
            raise ToolError(f"{message}: {_truncated(body)}" if body else f"{message}.", tool=name) from error
        except httpx2.RequestError as error:
            raise ToolError(
                f"{name}: the request to {self.request} failed before the API answered ({type(error).__name__}).",
                tool=name,
            ) from error
        except ValidationError as error:
            raise ToolError(
                f"{name}: the API's answer to {self.request} doesn't fit the endpoint's return annotation: "
                f"{_problems(error, values=False)}.",
                tool=name,
            ) from error

    def dump(self, result: Any) -> Any:
        """Return the endpoint's result as JSON-ready data."""
        return None if self.output is None else self.output.dump_python(result, mode="json")


# --- Building a tool ----------------------------------------------------------
# What each HTTP method implies, for the hints. POST is in none of them: it
# usually adds something, so it's neither read-only nor idempotent, and not
# destructive either, which is for replacing or removing what's there.
_READ_ONLY = frozenset({"GET", "HEAD", "OPTIONS"})
_IDEMPOTENT = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_DESTRUCTIVE = frozenset({"PUT", "PATCH", "DELETE"})


def _tool(name: str, endpoint: Endpoint, function: Callable[..., Any]) -> Tool | None:
    """Return the tool for an endpoint, or ``None`` if a model can't use it."""
    returns = endpoint.signature.returns
    if endpoint.stream or returns.base_type is httpx2.Response:
        return None
    parameters = endpoint.signature.parameters[1:]
    try:
        adapter = _arguments_adapter(parameters)
        input_schema = _compact(adapter.json_schema(by_alias=False))
        returns_nothing = returns.base_type is None or returns.base_type is NoneType
        output = None if returns_nothing else TypeAdapter[Any](returns.annotation)
        output_schema = None if output is None else _compact(output.json_schema(mode="serialization"))
    except (PydanticSchemaGenerationError, PydanticInvalidForJsonSchema):
        return None
    doc = inspect.cleandoc(endpoint.signature.doc or "")
    argument_docs = _argument_docs(doc)
    for parameter_name, schema in input_schema.get("properties", {}).items():
        if "description" not in schema and parameter_name in argument_docs:
            schema["description"] = argument_docs[parameter_name]
    request = f"{endpoint.method} {endpoint.raw_path or '/'}"
    positional = tuple(p for p in parameters if p.kind is inspect.Parameter.POSITIONAL_ONLY)
    return Tool(
        name=name,
        description=_description(doc) or request,
        input_schema=input_schema,
        output_schema=output_schema,
        read_only=endpoint.method in _READ_ONLY,
        destructive=endpoint.method in _DESTRUCTIVE,
        idempotent=endpoint.method in _IDEMPOTENT,
        is_async=endpoint.signature.is_async,
        _call=_Call(function, adapter, output, positional, request),
    )


# Validates arguments by parameter name: a helper's alias is the name sent to
# the API, not the one a caller uses.
_BY_NAME = ConfigDict(validate_by_name=True, validate_by_alias=False)


def _arguments_adapter(parameters: Sequence[ParameterInfo]) -> TypeAdapter[dict[str, Any]]:
    """Return a validator of a model's arguments for these parameters.

    It validates a call to a stand-in with the endpoint's parameters, all
    keyword-only so a mapping fills them, and returns the arguments: the
    endpoint is called separately, so a response that doesn't fit isn't taken
    for arguments that don't.
    """

    def arguments(**values: Any) -> dict[str, Any]:
        return values

    arguments.__signature__ = inspect.Signature(  # pyright: ignore[reportFunctionMemberAccess]
        [
            inspect.Parameter(p.name, inspect.Parameter.KEYWORD_ONLY, default=p.default, annotation=p.annotation)
            for p in parameters
        ]
    )
    arguments.__annotations__ = {p.name: p.annotation for p in parameters}
    # Pydantic validates a call to a function, which its types don't allow.
    return TypeAdapter[dict[str, Any]](cast("Any", arguments), config=_BY_NAME)


# --- Error messages -----------------------------------------------------------
# How much of an error response's body a message shows.
_BODY_LIMIT = 2000


def _truncated(text: str) -> str:
    if len(text) <= _BODY_LIMIT:
        return text
    return f"{text[:_BODY_LIMIT]}... ({len(text) - _BODY_LIMIT} more characters)"


def _problems(error: ValidationError, *, values: bool) -> str:
    """Return each of Pydantic's errors as ``where: what``, without its URL.

    With ``values``, a value that's there but doesn't fit is shown too, short:
    it's the model's own argument. A response's values aren't.
    """
    problems: list[str] = []
    for problem in error.errors(include_url=False, include_context=False):
        where = ".".join(str(part) for part in problem["loc"]) or "the arguments"
        # A missing argument is reported as keyword-only, as the stand-in's are.
        if problem["type"].startswith("missing"):
            problems.append(f"{where}: is required")
            continue
        text = f"{where}: {problem['msg']}"
        if values:
            text += f" (got {problem['input']!r:.80})"
        problems.append(text)
    return "; ".join(problems)


# --- Descriptions -------------------------------------------------------------
# A Google-style section header, which ends a docstring's description.
_SECTION = re.compile(
    r"(Args|Arguments|Attributes|Example|Examples|Note|Notes|Raises|Returns|See Also|Warning|Warnings|Yields):"
)
# An argument's entry in ``Args:``: "name: text", or "name (type): text".
_ENTRY = re.compile(r"\*{0,2}(?P<name>\w+)(?:\s*\([^)]*\))?:\s*(?P<text>.*)")


def _description(doc: str) -> str:
    """Return a docstring up to its first section, such as ``Args:``."""
    lines = doc.splitlines()
    end = next((index for index, line in enumerate(lines) if _SECTION.fullmatch(line.strip())), len(lines))
    return "\n".join(lines[:end]).strip()


def _argument_docs(doc: str) -> dict[str, str]:
    """Return each argument's description from a docstring's ``Args:``.

    An entry's continuation lines, indented further, are joined to it.
    """
    lines = doc.splitlines()
    start = next((index + 1 for index, line in enumerate(lines) if line.strip() in {"Args:", "Arguments:"}), None)
    if start is None:
        return {}
    docs: dict[str, str] = {}
    entry_indent: int | None = None
    current: str | None = None
    for line in lines[start:]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            break
        entry_indent = indent if entry_indent is None else entry_indent
        if indent == entry_indent:
            match = _ENTRY.fullmatch(line.strip())
            if match is None:
                current = None
                continue
            name: str = match["name"]
            docs[name], current = match["text"], name
        elif current is not None:
            docs[current] = f"{docs[current]} {line.strip()}".strip()
    return docs


# --- Compact schemas ----------------------------------------------------------
# Keys whose value maps names to schemas, not a schema itself.
_SCHEMA_MAPS = frozenset({"$defs", "patternProperties", "properties"})
# Keys whose value is data, not a schema, so it's kept as it is.
_DATA = frozenset({"const", "default", "enum", "examples"})


def _compact(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON Schema without titles, with each ``$ref`` written in place.

    A definition that refers to itself, directly or not, can't be written in
    place, so it stays in ``$defs``, and so do the references to it.
    """
    definitions: dict[str, Any] = schema.get("$defs", {})
    kept: dict[str, Any] = {}
    compact = _inline({k: v for k, v in schema.items() if k != "$defs"}, definitions, frozenset(), kept)
    pending = [name for name in kept if kept[name] is None]
    while pending:
        for name in pending:
            kept[name] = _inline(definitions[name], definitions, frozenset({name}), kept)
        pending = [name for name in kept if kept[name] is None]
    if kept:
        compact["$defs"] = kept
    return compact


def _inline(node: Any, definitions: dict[str, Any], stack: frozenset[str], kept: dict[str, Any]) -> Any:
    """Return ``node`` with titles left out and references written in place.

    ``stack`` holds the definitions being written in place around ``node``: a
    reference to one of them is kept, and its name added to ``kept``.
    """
    if isinstance(node, list):
        return [_inline(item, definitions, stack, kept) for item in node]  # pyright: ignore[reportUnknownVariableType]
    if not isinstance(node, dict):
        return node
    reference = node.get("$ref")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if isinstance(reference, str) and reference.startswith("#/$defs/"):
        name = reference.removeprefix("#/$defs/")
        others = {k: v for k, v in node.items() if k != "$ref"}  # pyright: ignore[reportUnknownVariableType]
        if name in stack:
            kept.setdefault(name, None)
            return {"$ref": reference, **_inline(others, definitions, stack, kept)}
        return {
            **_inline(definitions[name], definitions, stack | {name}, kept),
            **_inline(others, definitions, stack, kept),
        }
    compact: dict[str, Any] = {}
    for key, value in node.items():  # pyright: ignore[reportUnknownVariableType]
        if key == "title":
            continue
        if key in _DATA:
            compact[key] = value
        elif key in _SCHEMA_MAPS and isinstance(value, dict):
            compact[key] = {
                sub_name: _inline(sub, definitions, stack, kept)
                for sub_name, sub in value.items()  # pyright: ignore[reportUnknownVariableType]
            }
        else:
            compact[key] = _inline(value, definitions, stack, kept)
    return compact
