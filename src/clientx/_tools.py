"""Describe a client's endpoints, and its ``@tool`` methods, as tools.

``list_tools(client)`` returns one ``Tool`` per endpoint on the client and the
resources mounted on it, and per method ``@tool`` marks there: a name, a
description, a JSON Schema of its arguments and of its result, hints about what
it does, its tags, and ``call()`` or ``acall()``.
Nothing here depends on an AI library, so an adapter for MCP or another
framework can build on it.

- Names: the attribute path from the client, joined with ``_``, so
  ``api.users.create`` is ``users_create``. An endpoint's second name in its
  class is left out: it's the same endpoint.
- Left out: an endpoint that streams (``-> Iterator[...]`` or
  ``stream=True``), returns the raw ``Response``, or has an argument with no
  JSON form, such as a binary file. A model can't use them well.
- Tool methods: ``@tool`` makes a method of a client or resource a tool, such
  as one that calls several endpoints and returns what a model needs at once.
  It needs a docstring, which is its description. Its hints are ``False``
  unless set, as there's no HTTP method to take them from. It's checked when
  it's decorated, and its kind (``def`` or ``async def``) when its class is
  defined, as an endpoint is. One whose arguments or result have no JSON form
  raises ``DefinitionError`` when it's listed, rather than being left out:
  it was made a tool on purpose.
- Descriptions: the docstring, up to its first section (``Args:``,
  ``Returns:``...), or else the method and path. A deprecated endpoint is
  still a tool: its description starts with ``Deprecated:`` and the
  message, so a model prefers the replacement, and ``Tool.deprecated`` holds the
  message, to leave it out by. An argument's description is
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
- Hints: each is worked out on its own, as the endpoint's ``tool_options=``
  setting, or else what its HTTP method implies (``ToolOptions`` lists them),
  so setting one never changes another. An endpoint can't be read-only and
  destructive.
- Errors: a failed call raises ``ToolError``, with a message written for a
  model and the original error as its cause. HTTP errors name the method and
  path template, never the host or query string, which can hold credentials.
  A tool method's requests aren't one endpoint's, so its HTTP errors name only
  the HTTP method.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import NoneType
from typing import TYPE_CHECKING, Any

import httpx2
from pydantic import PydanticSchemaGenerationError, TypeAdapter, ValidationError
from pydantic.errors import PydanticInvalidForJsonSchema

from clientx._registry import endpoint_for, register_tool_method, tool_method_for
from clientx._signature import NO_VALUE, ParameterKind, inspect_definition
from clientx._validation import arguments_adapter, describe_errors
from clientx.exceptions import ArgumentError, DefinitionError, ToolError

if TYPE_CHECKING:
    from clientx._client import AsyncClientX, ClientX
    from clientx._endpoint import Endpoint
    from clientx._signature import ParameterInfo, SignatureInfo


# --- Entry point --------------------------------------------------------------
def list_tools(client: ClientX | AsyncClientX) -> list[Tool]:
    """Return a tool for each endpoint a model can call, and each ``@tool``.

    Every endpoint on the client and the resources mounted on it is a tool,
    named by its attribute path (``users_create``), and so is every method
    there that ``@tool`` marks. An endpoint is left out if a model can't use it
    well:

    - one that streams, annotated ``-> Iterator[...]`` or with
      ``stream=True``;
    - one that returns the raw ``Response``: annotate what the API returns
      instead, such as a model or ``dict[str, Any]``;
    - one with an argument that has no JSON form, such as a binary file.

    An endpoint's or tool method's second name in its class is listed once.
    A deprecated endpoint is listed too: ``Tool.deprecated`` holds its message.

    Raises:
        DefinitionError: If a ``@tool`` method's arguments or result have no
            JSON form.
    """
    tools: list[Tool] = []
    _collect(client, "", tools, set())
    return tools


def _collect(owner: object, prefix: str, tools: list[Tool], seen: set[int]) -> None:
    """Add the tools on ``owner``, then those on its resources.

    ``seen`` holds each endpoint and tool method met so far, by ``id``, so a
    second name is left out.
    """
    for name, value in _members(type(owner)).items():
        definition = endpoint_for(value) or tool_method_for(value)
        if definition is None:
            if hasattr(type(value), "__clientx_prefix__"):  # A mounted resource.
                _collect(getattr(owner, name), f"{prefix}{name}_", tools, seen)
            continue
        if id(definition) in seen:
            continue
        seen.add(id(definition))
        if isinstance(definition, ToolMethod):
            tools.append(_method_tool(prefix + name, definition, getattr(owner, name)))
        elif (tool := _endpoint_tool(prefix + name, definition, getattr(owner, name))) is not None:
            tools.append(tool)


def _members(cls: type) -> dict[str, object]:
    """Return the attributes ``cls`` and its parents define, in class order."""
    members: dict[str, object] = {}
    for class_ in reversed(cls.__mro__):
        members.update(vars(class_))
    return members


# --- Tools --------------------------------------------------------------------
@dataclass(frozen=True, kw_only=True)
class Tool:
    """An endpoint or ``@tool`` method described for a model, and called.

    Each hint, ``read_only``, ``destructive`` or ``idempotent``, is worked out
    on its own: an endpoint's is its ``tool_options=`` setting, or else what its
    HTTP method implies, and a tool method's is its ``@tool`` setting, or else
    ``False``. ClientX doesn't act on them: they're for choosing tools, and for
    frameworks that show them to a model.

    Attributes:
        name: The attribute path from the client, joined with ``_``.
        description: What it does, from its docstring.
        input_schema: The JSON Schema of the arguments: an object with one
            property per parameter, named as in the method.
        output_schema: The JSON Schema of the result, or ``None`` for
            ``-> None``.
        read_only: Calling it changes nothing.
        destructive: It can delete or overwrite what's there. ``False`` means
            it only adds.
        idempotent: Calling it again with the same arguments has no further
            effect.
        tags: Its tags, its resource's first, to choose which tools to
            register by.
        deprecated: The endpoint's ``deprecated=`` message, or ``None``. The
            description starts with it too, so a model given the tool, or a
            client that shows only its first line, sees the replacement.
        is_async: It's ``async def``, so it's called with ``acall()``.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    read_only: bool
    destructive: bool
    idempotent: bool
    tags: tuple[str, ...]
    deprecated: str | None
    is_async: bool
    _call: _Call = field(repr=False, compare=False)

    def call(self, arguments: Mapping[str, Any] | None = None) -> Any:
        """Call it with a model's arguments; return JSON-ready data.

        Raises:
            ToolError: If the arguments don't fit, a request can't be sent or
                fails, or a response doesn't fit its endpoint's annotation.
            TypeError: If it's ``async def``: use ``acall()``.
        """
        if self.is_async:
            raise TypeError(f"Tool {self.name!r} is an async def endpoint: call it with acall().")
        args, kwargs = self._call.arguments(self.name, arguments)
        with self._call.errors(self.name):
            result = self._call.function(*args, **kwargs)
        return self._call.dump(result)

    async def acall(self, arguments: Mapping[str, Any] | None = None) -> Any:
        """Call the ``async def`` endpoint or method with a model's arguments.

        Raises:
            ToolError: As for ``call()``.
            TypeError: If it's a plain ``def``: use ``call()``.
        """
        if not self.is_async:
            raise TypeError(f"Tool {self.name!r} is a def endpoint: call it with call().")
        args, kwargs = self._call.arguments(self.name, arguments)
        with self._call.errors(self.name):
            result = await self._call.function(*args, **kwargs)
        return self._call.dump(result)


@dataclass(frozen=True)
class _Call:
    """What a tool needs to call its endpoint or method and report on it."""

    function: Callable[..., Any]
    adapter: TypeAdapter[dict[str, Any]]
    output: TypeAdapter[Any] | None
    positional: tuple[ParameterInfo, ...]
    request: str | None  # An endpoint's method and path template, for messages: "POST /users".

    def arguments(self, name: str, arguments: Mapping[str, Any] | None) -> tuple[list[Any], dict[str, Any]]:
        """Return the validated arguments the model gave, to call with.

        A positional-only parameter is passed by position, so one the model
        left out before one it gave gets its default.

        Raises:
            ToolError: If the arguments don't fit the parameters.
        """
        given = dict(arguments or {})
        try:
            validated = self.adapter.validate_python(given)
        except ValidationError as error:
            raise ToolError(
                f"The arguments don't fit {name}: {describe_errors(error, values=True)}. Nothing was sent.", tool=name
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
        what to fix. A tool method's request isn't one endpoint's, so its
        messages name only the HTTP method.
        """
        try:
            yield
        except ArgumentError as error:
            raise ToolError(f"{name} couldn't send its request: {error}", tool=name) from error
        except httpx2.HTTPStatusError as error:
            response = error.response
            target = self.request or f"a {error.request.method} request"
            message = f"{name}: the API answered {response.status_code} {response.reason_phrase} to {target}"
            body = response.text.strip()
            raise ToolError(f"{message}: {_truncated(body)}" if body else f"{message}.", tool=name) from error
        except httpx2.RequestError as error:
            target = f"the request to {self.request}" if self.request else "a request"
            raise ToolError(
                f"{name}: {target} failed before the API answered ({type(error).__name__}).", tool=name
            ) from error
        except ValidationError as error:
            what = (
                f"the API's answer to {self.request} doesn't fit the endpoint's return annotation"
                if self.request
                else "an answer from the API doesn't fit the type it was read into"
            )
            raise ToolError(f"{name}: {what}: {describe_errors(error, values=False)}.", tool=name) from error

    def dump(self, result: Any) -> Any:
        """Return the result as JSON-ready data."""
        return None if self.output is None else self.output.dump_python(result, mode="json")


# --- Building a tool ----------------------------------------------------------
def _endpoint_tool(name: str, endpoint: Endpoint, function: Callable[..., Any]) -> Tool | None:
    """Return the tool for an endpoint, or ``None`` if a model can't use it."""
    if endpoint.stream or endpoint.signature.returns.base_type is httpx2.Response:
        return None
    try:
        request = f"{endpoint.method} {endpoint.raw_path or '/'}"
        return _tool(name, endpoint, function, request=request, deprecated=endpoint.deprecated)
    except (PydanticSchemaGenerationError, PydanticInvalidForJsonSchema):
        return None


def _method_tool(name: str, tool_method: ToolMethod, function: Callable[..., Any]) -> Tool:
    """Return the tool for a ``@tool`` method.

    Raises:
        DefinitionError: If an argument or the result has no JSON form.
    """
    try:
        return _tool(name, tool_method, function, request=None, deprecated=None)
    except (PydanticSchemaGenerationError, PydanticInvalidForJsonSchema) as error:
        raise DefinitionError(
            f"Tool '{tool_method.signature.qualname}' can't be described for a model: each of its arguments, and its "
            f"result, needs a JSON form, unlike a binary file or a raw Response ({type(error).__name__})."
        ) from error


def _tool(
    name: str,
    definition: Endpoint | ToolMethod,
    function: Callable[..., Any],
    *,
    request: str | None,
    deprecated: str | None,
) -> Tool:
    """Return the tool for an endpoint or tool method.

    ``request`` is an endpoint's method and path template, its description when
    it has no docstring, or ``None`` for a tool method, which has a docstring.
    ``deprecated`` is an endpoint's deprecation message, which the description
    starts with.
    Pydantic's ``PydanticSchemaGenerationError`` or
    ``PydanticInvalidForJsonSchema`` propagates for a type with no JSON form.
    """
    signature = definition.signature
    parameters = signature.parameters[1:]
    returns = signature.returns
    adapter = arguments_adapter(parameters)
    input_schema = _compact(adapter.json_schema(by_alias=False))
    returns_nothing = returns.base_type is None or returns.base_type is NoneType
    output = None if returns_nothing else TypeAdapter[Any](returns.annotation)
    output_schema = None if output is None else _compact(output.json_schema(mode="serialization"))
    doc = inspect.cleandoc(signature.doc or "")
    argument_docs = _argument_docs(doc)
    for parameter_name, schema in input_schema.get("properties", {}).items():
        if "description" not in schema and parameter_name in argument_docs:
            schema["description"] = argument_docs[parameter_name]
    positional = tuple(p for p in parameters if p.kind is inspect.Parameter.POSITIONAL_ONLY)
    description = _description(doc) or request or ""
    if deprecated is not None:
        description = f"Deprecated: {deprecated}\n\n{description}"
    return Tool(
        name=name,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
        read_only=definition.read_only,
        destructive=definition.destructive,
        idempotent=definition.idempotent,
        tags=tuple(definition.tags),
        deprecated=deprecated,
        is_async=signature.is_async,
        _call=_Call(function, adapter, output, positional, request),
    )


# --- Tool methods -------------------------------------------------------------
@dataclass(slots=True)
class ToolMethod:
    """A method ``@tool`` made a tool, with what ``list_tools`` needs of it.

    Attributes:
        signature: The method's analysed signature. The first parameter
            receives the client or resource.
        read_only: ``@tool``'s ``read_only`` hint.
        destructive: ``@tool``'s ``destructive`` hint.
        idempotent: ``@tool``'s ``idempotent`` hint.
        tags: ``@tool``'s tags, each once. A resource puts its own in front
            when its class is defined.
    """

    signature: SignatureInfo
    read_only: bool
    destructive: bool
    idempotent: bool
    tags: list[str]


def tool[F: Callable[..., Any]](
    *,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    tags: list[str] | None = None,
) -> Callable[[F], F]:
    """Make a method of a client or resource a tool, beside its endpoints.

    For a tool that isn't one endpoint, such as one that calls several and
    returns what a model needs in one call. ``list_tools`` lists it as it lists
    an endpoint: named by its attribute path, described by its docstring, with
    schemas from its signature. The method itself is returned unchanged.

    The hints mean what ``ToolOptions`` says. They're ``False`` unless set, as
    there's no HTTP method to take them from. A resource's tags go in front of
    ``tags``. An endpoint is a tool already: set its hints with its verb's
    ``tool_options=``.

    Like an endpoint, a tool method is ``def`` on a ``ClientX`` or
    ``Resource``, and ``async def`` on an ``AsyncClientX`` or
    ``AsyncResource``, which its class checks when it's defined.

    Raises:
        DefinitionError: If the method is an endpoint, has no docstring or no
            return annotation, has no positional first parameter, takes
            ``*args`` or ``**kwargs``, or is read-only and destructive.
    """

    def decorator(func: F) -> F:
        if endpoint_for(func) is not None:  # @tool over the verb.
            raise DefinitionError(
                f"'{func.__qualname__}' is an endpoint, so it's a tool already: instead of @tool, set its hints "
                "with its verb's `tool_options=`."
            )
        tool_method = ToolMethod(
            signature=inspect_definition(func, "Tool"),
            read_only=read_only,
            destructive=destructive,
            idempotent=idempotent,
            tags=list(dict.fromkeys(tags or ())),
        )
        _check_tool_method(tool_method)
        register_tool_method(func, tool_method)
        return func

    return decorator


def _check_tool_method(tool_method: ToolMethod) -> None:
    """Raise ``DefinitionError`` unless a ``@tool`` method can be a tool.

    It needs a docstring, which is its description: there's no method and path
    to fall back on. It needs a return annotation, for its output schema and
    to turn its result into JSON. A model passes arguments by name, so each
    parameter after the first, which receives the client or resource, is one
    argument.
    """
    signature = tool_method.signature
    name = signature.qualname
    if not _description(inspect.cleandoc(signature.doc or "")):
        raise DefinitionError(
            f"Tool '{name}' needs a docstring: it's the tool's description, which a model reads to choose it."
        )
    if signature.returns.annotation is NO_VALUE:
        raise DefinitionError(
            f"Tool '{name}' needs a return annotation: it's the tool's output schema, and says how its result "
            "becomes JSON. Use `-> None` if it returns nothing."
        )
    first = signature.parameters[0] if signature.parameters else None
    if first is None or first.kind not in (ParameterKind.POSITIONAL_ONLY, ParameterKind.POSITIONAL_OR_KEYWORD):
        raise DefinitionError(
            f"Tool '{name}' needs a positional first parameter, such as `self`, for the client or resource it's "
            "called on."
        )
    for parameter in signature.parameters[1:]:
        if parameter.kind in (ParameterKind.VAR_POSITIONAL, ParameterKind.VAR_KEYWORD):
            star = "*" if parameter.kind is ParameterKind.VAR_POSITIONAL else "**"
            raise DefinitionError(
                f"Tool '{name}' can't take `{star}{parameter.name}`: a model passes each argument by name, so each "
                "needs a parameter of its own."
            )
    if tool_method.read_only and tool_method.destructive:
        raise DefinitionError(
            f"Tool '{name}' can't be both read-only and destructive: a read-only tool changes nothing."
        )


# --- Error messages -----------------------------------------------------------
# How much of an error response's body a message shows.
_BODY_LIMIT = 2000


def _truncated(text: str) -> str:
    if len(text) <= _BODY_LIMIT:
        return text
    return f"{text[:_BODY_LIMIT]}... ({len(text) - _BODY_LIMIT} more characters)"


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
