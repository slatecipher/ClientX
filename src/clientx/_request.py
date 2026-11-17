"""Build the request an endpoint call sends.

When the client or resource class that declares an endpoint is defined, ``plan_request``
works out its ``RequestPlan`` from its path template and parameters, and checks that they fit
together. On each call, ``RequestPlan.build`` turns the call's arguments into the URL path and
the other ``build_request`` arguments, without reading annotations again.

Where each parameter goes is decided once, the way FastAPI decides it:

1. A parameter that a path placeholder names fills it. It must be a plain value.
2. A parameter with a ``clientx.arguments`` helper in its outermost ``Annotated`` goes where
   the helper says. A helper anywhere else in its type, as in ``Annotated[str, Header()] | None``,
   is an error.
3. Any other parameter goes to the JSON body if its type is a model, mapping, collection or
   dataclass, or a union with one of those, and to the query string otherwise.

A query parameter is a plain value, or a list of plain values, which repeats the key
(``?tag=a&tag=b``). A header is a plain value. Each is sent under its helper's alias, or else
under the parameter's name, with ``_`` turned into ``-`` for a header. A ``None`` value is left
out. ``_to_text`` turns values into text. JSON, raw bodies, forms, files, and models or mappings
with a helper aren't sent yet.

The path template, such as ``"/users/{user_id}"``, is split into literal text and placeholders
in the plan. Each call fills the placeholders with its arguments, encoded so that a value
can't change which path is called.

A placeholder is ``{name}``, filled with one path segment, or ``{name:path}``, whose value
keeps its slashes, for values such as file paths. ``{{`` and ``}}`` are literal braces. Any
other brace is a mistake, so ``{user-id}`` fails when the class is defined rather than being
sent as it's written.
"""

import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, is_dataclass
from string import Formatter
from types import NoneType, UnionType
from typing import Any, TypeAliasType, Union, cast, get_args, get_origin
from urllib.parse import quote

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from clientx._arguments import get_argument_location
from clientx._signature import ParameterInfo, unwrap_annotated
from clientx._types import BuildRequestKwargs, HttpxArgument
from clientx.exceptions import ArgumentError, DefinitionError

# The end of each path template error message: how to write one that works.
_SYNTAX = (
    "A placeholder is {name}, for one path segment, or {name:path}, for a value that keeps its "
    "slashes, where name is a parameter's name. Write a literal brace as {{ or }}."
)

# `quote` leaves dots alone, so a `.` or `..` value is encoded here: it can't move up the path.
_DOT_SEGMENTS = {".": "%2E", "..": "%2E%2E"}

# How deep `_arms` follows a union inside a union: a stop for a `type` alias that contains itself.
_MAX_UNION_DEPTH = 100


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
class PlannedParameter:
    """Where one parameter's value goes in the request, and the name it's sent under.

    Attributes:
        name: The parameter's name, and its key in the call's arguments.
        part: The ``build_request`` argument it goes to: ``params`` or ``headers``, for now.
        key: The name it's sent under: the query parameter's or the header's name.
        many: Whether the value is a list of values, sent as a repeated query parameter.
    """

    name: str
    part: HttpxArgument
    key: str
    many: bool = False


@dataclass(frozen=True, slots=True)
class RequestPlan:
    """How an endpoint call's arguments become its request, worked out once, when its class is defined.

    Attributes:
        path: The path template, split into literal text and placeholders.
        parameters: Where the parameters that aren't in the path go: the query parameters
            and headers, for now.
    """

    path: tuple[str | Placeholder, ...]
    parameters: tuple[PlannedParameter, ...] = ()

    def build(self, arguments: Mapping[str, object]) -> tuple[str, BuildRequestKwargs]:
        """Return the URL path and the ``build_request`` arguments that carry one call's arguments.

        Args:
            arguments: The call's arguments by parameter name, as ``Endpoint.bind`` returns them.

        Raises:
            ArgumentError: If a value would change which path is called; see ``_encode_path_value``.
        """
        params: dict[str, str | list[str]] = {}
        headers: dict[str, str] = {}
        for parameter in self.parameters:
            value = arguments[parameter.name]
            if value is None:
                # Left out: httpx2 would send `?key=`, and rejects None as a header value.
                continue
            if parameter.part is HttpxArgument.HEADERS:
                headers[parameter.key] = _to_text(value)
            elif parameter.many:
                params[parameter.key] = [_to_text(item) for item in cast("Iterable[object]", value)]
            else:
                params[parameter.key] = _to_text(value)
        request_arguments: BuildRequestKwargs = {}
        if params:
            request_arguments["params"] = params
        if headers:
            request_arguments["headers"] = headers
        return _render_path(self.path, arguments), request_arguments


def plan_request(template: str, parameters: Sequence[ParameterInfo]) -> RequestPlan:
    """Work out an endpoint's ``RequestPlan`` from its full path template and its parameters.

    Args:
        template: The path template, with any resource prefix joined on.
        parameters: The parameters that take the call's arguments: all but the first one,
            which receives the client or resource.

    Raises:
        DefinitionError: If the template is malformed or doesn't fit the parameters, a
            helper is nested inside a parameter's type, or a parameter's type can't go
            where it would be sent.
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
    planned: list[PlannedParameter] = []
    for parameter in parameters:
        if _has_nested_helper(parameter):
            raise DefinitionError(
                f"Parameter {parameter.name!r} has a helper inside its type. ClientX reads a helper only "
                "in the outermost Annotated, so move it there: for example, Annotated[str | None, Header()] "
                "rather than Annotated[str, Header()] | None."
            )
        placeholder = placeholders.get(parameter.name)
        if placeholder is not None:
            _check_path_parameter(parameter, placeholder, template)
        elif (planned_parameter := _plan_parameter(parameter, template)) is not None:
            planned.append(planned_parameter)
    return RequestPlan(path, tuple(planned))


def _check_path_parameter(parameter: ParameterInfo, placeholder: Placeholder, template: str) -> None:
    """Check that a parameter that fills a placeholder has no other helper, and is a plain value."""
    name, part = parameter.name, parameter.httpx_argument
    if part not in {None, HttpxArgument.URL}:
        raise DefinitionError(
            f"Parameter {name!r} fills {placeholder} in the path {template!r}, so it can't also go to the "
            f"request's {part}. Remove its helper, or rename the parameter or the placeholder."
        )
    if not all(_is_plain(arm) for arm in _arms(parameter.annotation)):
        raise DefinitionError(
            f"Parameter {name!r} fills {placeholder} in the path {template!r}, so it must be a plain value, "
            "such as str or int, not a model, mapping or collection."
        )


def _plan_parameter(parameter: ParameterInfo, template: str) -> PlannedParameter | None:
    """Work out where a parameter that isn't in the path goes, or return ``None`` if that part isn't sent yet.

    Raises:
        DefinitionError: If the parameter is marked ``Url()``, or its type can't go to the
            query string or the headers, where it would be sent.
    """
    name, part = parameter.name, parameter.httpx_argument
    if part is HttpxArgument.URL:
        raise DefinitionError(
            f"Parameter {name!r} is marked Url(), but the path {template!r} has no placeholder {{{name}}}. "
            "Add the placeholder, or remove Url()."
        )
    arms = _arms(parameter.annotation)
    if part is None:
        if not all(_is_plain(arm) for arm in arms):
            return None  # Inferred as JSON, which isn't sent yet.
        part = HttpxArgument.PARAMS
    if part not in {HttpxArgument.PARAMS, HttpxArgument.HEADERS}:
        return None  # Bodies, forms and files aren't sent yet.
    if all(_is_plain(arm) for arm in arms):
        return PlannedParameter(name, part, _key(parameter, part))
    if part is HttpxArgument.PARAMS and all(_is_plain_list(arm) for arm in arms):
        return PlannedParameter(name, part, _key(parameter, part), many=True)
    if len(arms) == 1 and _has_fields(arms[0]):
        return None  # A model or mapping, spread into the part, which isn't sent yet.
    if part is HttpxArgument.PARAMS:
        expected = "the query string, which takes a plain value, such as str or int, or a list of them"
    else:
        expected = "the headers, which take a plain value, such as str or int"
    raise DefinitionError(f"Parameter {name!r} goes to {expected}.")


def _key(parameter: ParameterInfo, part: HttpxArgument) -> str:
    """Return the name a query parameter or header is sent under.

    It's the helper's alias (``Query(alias="q")`` sets ``serialization_alias`` too), or else the
    parameter's name, with ``_`` turned into ``-`` for a header, as FastAPI's ``Header()`` does.
    """
    field_info = parameter.clientx_field_info
    if field_info is not None and field_info.serialization_alias:
        return field_info.serialization_alias
    return parameter.name.replace("_", "-") if part is HttpxArgument.HEADERS else parameter.name


def _has_nested_helper(parameter: ParameterInfo) -> bool:
    """Return whether a helper is inside the parameter's type, as in ``Annotated[str, Header()] | None``.

    A helper in the outermost ``Annotated`` isn't nested: ``ParameterInfo`` has already found it.
    """
    return any(_contains_helper(arg, frozenset()) for arg in get_args(parameter.base_type))


def _contains_helper(annotation: Any, seen: frozenset[TypeAliasType]) -> bool:
    """Return whether ``annotation``, or any type inside it, has a helper in an ``Annotated``.

    ``seen`` holds the ``type`` aliases already expanded on the way here, so one that contains
    itself, such as ``type Value = dict[str, Value] | str``, is expanded only once.
    """
    alias = annotation if isinstance(annotation, TypeAliasType) else get_origin(annotation)
    if isinstance(alias, TypeAliasType):
        if alias in seen:
            return False
        seen |= {alias}
    base, metadata = unwrap_annotated(annotation)
    if any(get_argument_location(meta) is not None for meta in metadata):
        return True
    return any(_contains_helper(arg, seen) for arg in get_args(base))


def _arms(annotation: Any, depth: int = 0) -> list[Any]:
    """Return the types a value of ``annotation`` can have: a union's members, without ``None``.

    Each comes without ``Annotated`` or a ``type`` alias, and a union inside a union is flattened.
    A type that isn't a union is the only one.
    """
    base, _ = unwrap_annotated(annotation)
    if base is NoneType:
        return []
    if get_origin(base) not in {Union, UnionType} or depth > _MAX_UNION_DEPTH:
        return [base]
    return [arm for member in get_args(base) for arm in _arms(member, depth + 1)]


def _is_plain(annotation: Any) -> bool:
    """Return whether a value of this type is sent as one piece of text.

    It is unless it's a model, a collection (a mapping, list, tuple, set...) or a dataclass.
    ``str`` and ``bytes`` are plain, and so are ``Any`` and a missing annotation.
    """
    cls = _class_of(annotation)
    if cls is None or issubclass(cls, str | bytes | bytearray):
        return True
    return not (issubclass(cls, BaseModel | Collection) or is_dataclass(cls))


def _is_plain_list(annotation: Any) -> bool:
    """Return whether the type is a collection of plain values, such as ``list[str]``, but not a mapping."""
    cls = _class_of(annotation)
    if cls is None or _is_plain(annotation) or not issubclass(cls, Collection) or issubclass(cls, Mapping):
        return False
    return all(_is_plain(arm) for item in get_args(annotation) if item is not Ellipsis for arm in _arms(item))


def _has_fields(annotation: Any) -> bool:
    """Return whether a value of the type has named fields: it's a model, a mapping or a dataclass."""
    cls = _class_of(annotation)
    return cls is not None and (issubclass(cls, BaseModel | Mapping) or is_dataclass(cls))


def _class_of(annotation: Any) -> type[Any] | None:
    """Return the class a type stands for, such as ``list`` for ``list[str]``, or ``None`` if it isn't one.

    ``Literal["a"]`` and a ``TypeVar``, for example, aren't classes.
    """
    cls: object = get_origin(annotation) or annotation
    return cast("type[Any]", cls) if isinstance(cls, type) else None


def _to_text(value: object) -> str:
    """Return ``value`` as the text that's sent for it, in a path, a query string or a header.

    An ``Enum`` becomes its value, a ``datetime`` ISO 8601 text, a ``UUID`` its string, and
    a number or bool JSON text (``2``, ``true``). Any other object uses ``str``.
    """
    jsonable = to_jsonable_python(value, fallback=str)
    return jsonable if isinstance(jsonable, str) else json.dumps(jsonable)


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

    The value becomes text as ``_to_text`` says. Then every character that isn't unreserved
    is percent-encoded, slashes too unless the placeholder keeps them, so a value can't add
    path segments, a query string or a fragment. A ``.`` or ``..`` segment is encoded too,
    so it can't move up the path.

    Raises:
        ArgumentError: If the value is ``None`` or empty, or, for a ``{name:path}``
            placeholder, has an empty segment. Each would call a different path:
            ``/users/{user_id}`` with ``""`` would call ``/users/``.
    """
    if value is None:
        raise _path_value_error(placeholder, value, "None would be sent as 'null'")
    text = _to_text(value)
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
