"""Build the request an endpoint call sends.

When the client or resource class that declares an endpoint is defined, ``plan_request``
works out its ``RequestPlan`` from its path template and parameters, and checks that they fit
together. On each call, ``RequestPlan.build`` turns the call's arguments into the URL path and
the other ``build_request`` arguments, without reading annotations again.

The path template, such as ``"/users/{user_id}"``, is split into literal text and placeholders
in the plan. Each call fills the placeholders with its arguments, encoded so that a value
can't change which path is called.

A placeholder is ``{name}``, filled with one path segment, or ``{name:path}``, whose value
keeps its slashes, for values such as file paths. ``{{`` and ``}}`` are literal braces. Any
other brace is a mistake, so ``{user-id}`` fails when the class is defined rather than being
sent as it's written.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from string import Formatter
from urllib.parse import quote

from pydantic_core import to_jsonable_python

from clientx._signature import ParameterInfo
from clientx._types import BuildRequestKwargs, HttpxArgument
from clientx.exceptions import ArgumentError, DefinitionError

# The end of each path template error message: how to write one that works.
_SYNTAX = (
    "A placeholder is {name}, for one path segment, or {name:path}, for a value that keeps its "
    "slashes, where name is a parameter's name. Write a literal brace as {{ or }}."
)

# `quote` leaves dots alone, so a `.` or `..` value is encoded here: it can't move up the path.
_DOT_SEGMENTS = {".": "%2E", "..": "%2E%2E"}


@dataclass(frozen=True, slots=True)
class Placeholder:
    """A ``{name}`` or ``{name:path}`` placeholder in a path template.

    Attributes:
        name: The name of the parameter whose value fills it.
        keep_slashes: Whether the value keeps its slashes, so it can fill several
            segments: the placeholder is ``{name:path}``.
    """

    name: str
    keep_slashes: bool

    def __str__(self) -> str:
        """Return the placeholder as it's written in the template, for error messages."""
        return f"{{{self.name}:path}}" if self.keep_slashes else f"{{{self.name}}}"


@dataclass(frozen=True, slots=True)
class RequestPlan:
    """How an endpoint call's arguments become its request, worked out once, when its class is defined.

    Attributes:
        path: The path template, split into literal text and placeholders.
    """

    path: tuple[str | Placeholder, ...]

    def build(self, arguments: Mapping[str, object]) -> tuple[str, BuildRequestKwargs]:
        """Return the URL path and the ``build_request`` arguments that carry one call's arguments.

        Args:
            arguments: The call's arguments by parameter name, as ``Endpoint.bind`` returns them.

        Raises:
            ArgumentError: If a value would change which path is called; see ``_encode_path_value``.
        """
        return _render_path(self.path, arguments), {}


def plan_request(template: str, parameters: Sequence[ParameterInfo]) -> RequestPlan:
    """Work out an endpoint's ``RequestPlan`` from its full path template and its parameters.

    Args:
        template: The path template, with any resource prefix joined on.
        parameters: The parameters that take the call's arguments: all but the first one,
            which receives the client or resource.

    Raises:
        DefinitionError: If the template is malformed, a placeholder names no parameter, a
            parameter marked ``Url()`` has no placeholder, or a placeholder's parameter has a
            helper for another part of the request.
    """
    path = _parse_path(template)
    placeholders = {part.name: part for part in path if isinstance(part, Placeholder)}
    names = {parameter.name for parameter in parameters}
    for name, placeholder in placeholders.items():
        if name not in names:
            raise DefinitionError(
                f"Path {template!r} has the placeholder {placeholder}, but no parameter is named {name!r}. "
                "Add the parameter, or remove the placeholder."
            )
    for parameter in parameters:
        name, part = parameter.name, parameter.httpx_argument
        if name in placeholders and part not in {None, HttpxArgument.URL}:
            raise DefinitionError(
                f"Parameter {name!r} fills {placeholders[name]} in the path {template!r}, so it can't also "
                f"go to the request's {part}. Remove its helper, or rename the parameter or the placeholder."
            )
        if name not in placeholders and part is HttpxArgument.URL:
            raise DefinitionError(
                f"Parameter {name!r} is marked Url(), but the path {template!r} has no placeholder {{{name}}}. "
                "Add the placeholder, or remove Url()."
            )
    return RequestPlan(path)


def _parse_path(template: str) -> tuple[str | Placeholder, ...]:
    """Split a path template into literal text and placeholders, in order.

    ``string.Formatter`` parses it, so the syntax is Python's format string syntax, limited
    to ``{name}`` and ``{name:path}``. ``{{`` and ``}}`` become literal braces.

    Raises:
        DefinitionError: If a brace is neither part of a placeholder nor doubled, or a
            placeholder isn't ``{name}`` or ``{name:path}`` with a valid parameter name:
            ``{id:int}``, ``{user-id}``, ``{a.b}``, ``{c[0]}``, ``{d!r}`` and ``{}`` all raise.
    """
    try:
        fields = list(Formatter().parse(template))
    except ValueError as error:
        raise DefinitionError(f"Path {template!r} has a brace that isn't part of a placeholder. {_SYNTAX}") from error
    parts: list[str | Placeholder] = []
    for text, name, spec, conversion in fields:
        # Text after a `{{` or `}}` comes back as a separate piece: join it to the text before.
        if text and parts and isinstance(last := parts[-1], str):
            parts[-1] = last + text
        elif text:
            parts.append(text)
        if name is None:
            continue
        if not name.isidentifier() or conversion is not None or spec not in {"", "path"}:
            written = "{" + name + (f"!{conversion}" if conversion else "") + (f":{spec}" if spec else "") + "}"
            raise DefinitionError(f"Path {template!r}: ClientX can't fill the placeholder {written}. {_SYNTAX}")
        parts.append(Placeholder(name, keep_slashes=spec == "path"))
    return tuple(parts)


def _render_path(parts: tuple[str | Placeholder, ...], values: Mapping[str, object]) -> str:
    """Return the path, with each placeholder filled with its parameter's encoded value.

    Args:
        parts: The template, as ``_parse_path`` returns it.
        values: The call's arguments by parameter name. It has a value for every
            placeholder, because each placeholder names one of the endpoint's parameters.

    Raises:
        ArgumentError: If a value would change which path is called; see ``_encode_path_value``.
    """
    return "".join(part if isinstance(part, str) else _encode_path_value(part, values[part.name]) for part in parts)


def _encode_path_value(placeholder: Placeholder, value: object) -> str:
    """Return ``value`` as percent-encoded text for ``placeholder``.

    The value becomes text first: an ``Enum`` its value, a ``datetime`` ISO 8601 text, a
    ``UUID`` its string, and a number or bool JSON text (``2``, ``true``). Any other object
    uses ``str``. Then every character that isn't unreserved is percent-encoded, slashes too
    unless the placeholder keeps them, so a value can't add path segments, a query string or
    a fragment. A ``.`` or ``..`` segment is encoded too, so it can't move up the path.

    Raises:
        ArgumentError: If the value is ``None`` or empty, or, for a ``{name:path}``
            placeholder, has an empty segment. Each would call a different path:
            ``/users/{user_id}`` with ``""`` would call ``/users/``.
    """
    if value is None:
        raise _path_value_error(placeholder, value, "None would be sent as 'null'")
    jsonable = to_jsonable_python(value, fallback=str)
    text = jsonable if isinstance(jsonable, str) else json.dumps(jsonable)
    if not text:
        raise _path_value_error(placeholder, value, "an empty value would remove the segment")
    segments = text.split("/") if placeholder.keep_slashes else [text]
    if "" in segments:
        raise _path_value_error(placeholder, value, "a leading, trailing or doubled slash leaves an empty segment")
    return "/".join(_DOT_SEGMENTS.get(segment) or quote(segment, safe="") for segment in segments)


def _path_value_error(placeholder: Placeholder, value: object, problem: str) -> ArgumentError:
    """Return the error for a value that would call a different path, naming the placeholder and the problem."""
    return ArgumentError(
        f"Can't fill {placeholder} with {value!r}: {problem}, so a different path would be called. "
        "No request was sent.",
        parameter=placeholder.name,
    )
