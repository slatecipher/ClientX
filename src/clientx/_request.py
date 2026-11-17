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

A query parameter or form field is a plain value, or a list of plain values, which repeats
the key (``?tag=a&tag=b``). A header is a plain value. A file is passed to httpx2 as it is.
Each is sent under its helper's alias, or else under the parameter's name, with ``_`` turned
into ``-`` for a header. ``_to_text`` turns values into text.

The body is one kind: JSON, raw content (one ``Body()`` parameter), or a form (``Form()``
parameters, and ``File()`` ones for a multipart form). A lone JSON parameter that's a model,
mapping or list is the whole JSON body; any other JSON parameter is a field of a JSON object,
under its alias or name. A ``None`` value is left out everywhere, so an optional parameter
that isn't passed isn't sent.

A model, dataclass or mapping marked ``Query()``, ``Header()`` or ``Form()`` is spread into that
part: each field is a separate value, under its alias or name (with ``_`` turned into ``-`` for
a header), and each item of a mapping is sent under its own key. Each field follows the part's
rule, as a parameter would. A helper on a model's field is an error: the parameter's helper
decides where all of its fields go.

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
from dataclasses import fields as dataclass_fields
from string import Formatter
from types import NoneType, UnionType
from typing import Any, TypeAliasType, Union, cast, get_args, get_origin, get_type_hints
from urllib.parse import quote

from pydantic import BaseModel
from pydantic_core import PydanticUndefined, to_jsonable_python

from clientx._arguments import get_argument_location
from clientx._signature import ParameterInfo, unwrap_annotated
from clientx._types import BuildRequestKwargs, HttpxArgument, RequestContent
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

# The kind of body each part makes, for the one-kind-of-body check. A form's fields and files
# make one multipart body together.
_BODY_KINDS = {
    HttpxArgument.JSON: "JSON",
    HttpxArgument.CONTENT: "raw content",
    HttpxArgument.DATA: "a form",
    HttpxArgument.FILES: "a form",
}

# What each part that takes text accepts, for error messages.
_TEXT_PARTS = {
    HttpxArgument.PARAMS: "the query string, which takes a plain value, such as str or int, or a list of them",
    HttpxArgument.DATA: "the form, which takes a plain value, such as str or int, or a list of them",
    HttpxArgument.HEADERS: "the headers, which take a plain value, such as str or int",
}


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
        part: The ``build_request`` argument it goes to, such as ``params`` or ``json``.
        key: The name it's sent under: the query parameter's, header's, form field's, file's,
            or JSON field's name.
        many: Whether the value is a list of values, sent as a repeated query parameter or
            form field.
    """

    name: str
    part: HttpxArgument
    key: str
    many: bool = False

    def encode(self, value: object) -> object:
        """Return ``value`` as httpx2 takes it for this parameter's part.

        A file is passed as it is, and a JSON field becomes JSON-ready data, by the value's own
        type and with aliases. Anything else becomes text, or a list of texts for a list.
        """
        if self.part is HttpxArgument.FILES:
            return value
        if self.part is HttpxArgument.JSON:
            return to_jsonable_python(value, by_alias=True)
        if self.many:
            return [_to_text(item) for item in cast("Iterable[object]", value)]
        return _to_text(value)


@dataclass(frozen=True, slots=True)
class SpreadParameter:
    """A model, dataclass or mapping parameter whose fields are sent as separate values in one part.

    Attributes:
        name: The parameter's name, and its key in the call's arguments.
        part: The ``build_request`` argument its fields go to: ``params``, ``headers`` or ``data``.
        keys: For a model or dataclass, each field's attribute name and the key it's sent
            under. ``None`` for a mapping, whose own keys are sent as they are.
    """

    name: str
    part: HttpxArgument
    keys: tuple[tuple[str, str], ...] | None = None

    def encode(self, value: object) -> dict[str, object]:
        """Return the value's fields as httpx2 takes them for this part, by key.

        The value becomes JSON-ready data first, so a model's own serializers apply. Then each
        field becomes text, or a list of texts for a list. A field that's ``None`` is left out.
        """
        if self.keys is None:
            items = cast("dict[object, object]", to_jsonable_python(dict(cast("Mapping[object, object]", value))))
            pairs = [(str(key), item) for key, item in items.items()]
        else:
            fields = cast("dict[str, object]", to_jsonable_python(value, by_alias=False))
            pairs = [(key, fields.get(attribute)) for attribute, key in self.keys]
        return {key: _field_text(item) for key, item in pairs if item is not None}


@dataclass(frozen=True, slots=True)
class RequestPlan:
    """How an endpoint call's arguments become its request, worked out once, when its class is defined.

    Attributes:
        path: The path template, split into literal text and placeholders.
        parameters: The parameters sent under a name (query parameters, headers, form
            fields, files, and the fields of a JSON object), and the ones spread into a part,
            in signature order.
        body: The parameter that's the whole body, or ``None``: the raw content, or a lone
            JSON parameter that's a model, mapping or list. Its ``key`` isn't used.
    """

    path: tuple[str | Placeholder, ...]
    parameters: tuple[PlannedParameter | SpreadParameter, ...] = ()
    body: PlannedParameter | None = None

    def build(self, arguments: Mapping[str, object]) -> tuple[str, BuildRequestKwargs]:
        """Return the URL path and the ``build_request`` arguments that carry one call's arguments.

        A ``None`` value is left out: httpx2 would send ``?key=`` or an empty form field, and
        rejects ``None`` as a header. A ``None`` body means no body.

        Args:
            arguments: The call's arguments by parameter name, as ``Endpoint.bind`` returns them.

        Raises:
            ArgumentError: If a value would change which path is called; see ``_encode_path_value``.
        """
        fields: dict[HttpxArgument, dict[str, object]] = {}
        for parameter in self.parameters:
            value = arguments[parameter.name]
            if value is None:
                continue
            part_fields = fields.setdefault(parameter.part, {})
            if isinstance(parameter, SpreadParameter):
                # When keys clash, the later parameter wins, as in dict.update.
                part_fields.update(parameter.encode(value))
            else:
                part_fields[parameter.key] = parameter.encode(value)
        # Each part's value is build_request's argument name: "params", "headers", "data", "files" or "json".
        request_arguments = cast(
            "BuildRequestKwargs", {part.value: values for part, values in fields.items() if values}
        )
        if self.body is not None and (value := arguments[self.body.name]) is not None:
            if self.body.part is HttpxArgument.CONTENT:
                request_arguments["content"] = cast("RequestContent", value)
            else:
                request_arguments["json"] = to_jsonable_python(value, by_alias=True)
        return _render_path(self.path, arguments), request_arguments


def plan_request(template: str, parameters: Sequence[ParameterInfo]) -> RequestPlan:
    """Work out an endpoint's ``RequestPlan`` from its full path template and its parameters.

    Args:
        template: The path template, with any resource prefix joined on.
        parameters: The parameters that take the call's arguments: all but the first one,
            which receives the client or resource.

    Raises:
        DefinitionError: If the template is malformed or doesn't fit the parameters, a
            helper is nested inside a parameter's type or has a default, the parameters
            make more than one kind of body, or a parameter's type can't go where it
            would be sent.
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

    # First, which part each parameter that isn't in the path goes to.
    placed: list[tuple[ParameterInfo, HttpxArgument]] = []
    for parameter in parameters:
        _check_helper(parameter)
        placeholder = placeholders.get(parameter.name)
        if placeholder is not None:
            _check_path_parameter(parameter, placeholder, template)
        else:
            placed.append((parameter, _part_of(parameter, template)))
    _check_one_body(placed)

    # Then how each is sent: as the whole body, or under a name.
    json_parameters = [parameter for parameter, part in placed if part is HttpxArgument.JSON]
    lone_json = json_parameters[0] if len(json_parameters) == 1 else None
    body: PlannedParameter | None = None
    planned: list[PlannedParameter | SpreadParameter] = []
    for parameter, part in placed:
        if part is HttpxArgument.CONTENT or (parameter is lone_json and not _all_plain(parameter.annotation)):
            body = PlannedParameter(parameter.name, part, parameter.name)
        else:
            planned.append(_plan_keyed(parameter, part))
    return RequestPlan(path, tuple(planned), body)


def _check_helper(parameter: ParameterInfo) -> None:
    """Check that a parameter's helper is in its outermost ``Annotated`` and has no default of its own.

    Also check that no field of a model parameter has a helper: the parameter's helper, or its
    inferred part, decides where the model goes.

    Raises:
        DefinitionError: If a model field has a helper, the helper is nested inside the parameter's
            type, or the helper has a default.
    """
    for arm in _arms(parameter.annotation):
        cls = _class_of(arm)
        if cls is None or not issubclass(cls, BaseModel):
            continue
        for field_name, field_info in cls.model_fields.items():
            if get_argument_location(field_info) is not None:
                raise DefinitionError(
                    f"Field {field_name!r} of {cls.__name__} has a clientx.arguments helper, but ClientX reads "
                    f"helpers only on endpoint parameters. Put the helper on parameter {parameter.name!r} "
                    f"instead, as in Annotated[{cls.__name__}, Query()]: all of the model's fields then go there."
                )
    if _has_nested_helper(parameter):
        raise DefinitionError(
            f"Parameter {parameter.name!r} has a helper inside its type. ClientX reads a helper only "
            "in the outermost Annotated, so move it there: for example, Annotated[str | None, Header()] "
            "rather than Annotated[str, Header()] | None."
        )
    field_info = parameter.clientx_field_info
    if field_info is not None and (field_info.default is not PydanticUndefined or field_info.default_factory):
        raise DefinitionError(
            f"Parameter {parameter.name!r} has a default inside its helper, where ClientX doesn't read it. "
            "Put the default after = instead, as in page: Annotated[int, Query()] = 1."
        )


def _check_path_parameter(parameter: ParameterInfo, placeholder: Placeholder, template: str) -> None:
    """Check that a parameter that fills a placeholder has no other helper, and is a plain value.

    Raises:
        DefinitionError: If the parameter has a helper other than ``Url()``, or isn't a plain value.
    """
    name, part = parameter.name, parameter.httpx_argument
    if part not in {None, HttpxArgument.URL}:
        raise DefinitionError(
            f"Parameter {name!r} fills {placeholder} in the path {template!r}, so it can't also go to the "
            f"request's {part}. Remove its helper, or rename the parameter or the placeholder."
        )
    if not _all_plain(parameter.annotation):
        raise DefinitionError(
            f"Parameter {name!r} fills {placeholder} in the path {template!r}, so it must be a plain value, "
            "such as str or int, not a model, mapping or collection."
        )


def _part_of(parameter: ParameterInfo, template: str) -> HttpxArgument:
    """Return the part a parameter that isn't in the path goes to: its helper's, or else the inferred one.

    Without a helper, a plain value goes to the query string, and anything else to JSON.

    Raises:
        DefinitionError: If the parameter is marked ``Url()``: it has no placeholder.
    """
    name, part = parameter.name, parameter.httpx_argument
    if part is HttpxArgument.URL:
        raise DefinitionError(
            f"Parameter {name!r} is marked Url(), but the path {template!r} has no placeholder {{{name}}}. "
            "Add the placeholder, or remove Url()."
        )
    if part is not None:
        return part
    return HttpxArgument.PARAMS if _all_plain(parameter.annotation) else HttpxArgument.JSON


def _check_one_body(placed: list[tuple[ParameterInfo, HttpxArgument]]) -> None:
    """Check that the parameters make one kind of body, and that at most one is the raw content.

    httpx2 sends only one body: given several, it silently drops the others.

    Raises:
        DefinitionError: If the parameters make more than one kind of body, or several are marked ``Body()``.
    """
    body_parameters = [(parameter.name, _BODY_KINDS[part]) for parameter, part in placed if part in _BODY_KINDS]
    if len({kind for _, kind in body_parameters}) > 1:
        listed = ", ".join(f"{name!r} ({kind})" for name, kind in body_parameters)
        raise DefinitionError(
            f"The parameters make more than one kind of body: {listed}. A request has one body: JSON, "
            "the raw content of one Body() parameter, or a form of Form() and File() parameters."
        )
    content = [repr(name) for name, kind in body_parameters if kind == _BODY_KINDS[HttpxArgument.CONTENT]]
    if len(content) > 1:
        raise DefinitionError(f"Parameters {', '.join(content)} are all marked Body(), but a request has one body.")


def _plan_keyed(parameter: ParameterInfo, part: HttpxArgument) -> PlannedParameter | SpreadParameter:
    """Plan a parameter that's sent under a name, or spread into its part.

    A JSON field or a file can be any value. A query parameter or form field is a plain value
    or a list of them, and a header a plain value. A model, dataclass or mapping for one of
    those parts is spread into it.

    Raises:
        DefinitionError: If the parameter's type, or one of its fields, can't go to its part.
    """
    name, key = parameter.name, _key(parameter, part)
    if part in {HttpxArgument.JSON, HttpxArgument.FILES}:
        return PlannedParameter(name, part, key)
    arms = _arms(parameter.annotation)
    if _takes_text(arms, part):
        return PlannedParameter(name, part, key, many=not all(_is_plain(arm) for arm in arms))
    if len(arms) == 1 and _has_fields(arms[0]):
        return _plan_spread(parameter, part, arms[0])
    raise DefinitionError(f"Parameter {name!r} goes to {_TEXT_PARTS[part]}.")


def _plan_spread(parameter: ParameterInfo, part: HttpxArgument, annotation: Any) -> SpreadParameter:
    """Plan a model, dataclass or mapping parameter whose fields are spread into ``part``.

    A model's or dataclass's field is sent under its alias or attribute name, with ``_`` turned
    into ``-`` for a header. A mapping's items are sent under their own keys.

    Raises:
        DefinitionError: If a field, or a mapping's value type, can't go to the part.
    """
    cls = cast("type[Any]", _class_of(annotation))
    if issubclass(cls, Mapping):
        args = get_args(annotation)
        if not _takes_text(_arms(args[1] if len(args) == 2 else Any), part):
            raise DefinitionError(
                f"Parameter {parameter.name!r} sends each item of the mapping to {_TEXT_PARTS[part]}; "
                "its value type isn't one."
            )
        return SpreadParameter(parameter.name, part)
    keys: list[tuple[str, str]] = []
    for attribute, (field_type, alias) in _fields_of(cls).items():
        if not _takes_text(_arms(field_type), part):
            raise DefinitionError(
                f"Parameter {parameter.name!r} sends each field of {cls.__name__} to {_TEXT_PARTS[part]}; "
                f"field {attribute!r} isn't one."
            )
        keys.append((attribute, alias or (attribute.replace("_", "-") if part is HttpxArgument.HEADERS else attribute)))
    return SpreadParameter(parameter.name, part, tuple(keys))


def _takes_text(arms: list[Any], part: HttpxArgument) -> bool:
    """Return whether values of these types can go to ``part``: plain values, or lists of them except in headers."""
    if all(_is_plain(arm) for arm in arms):
        return True
    return part is not HttpxArgument.HEADERS and all(_is_plain_list(arm) for arm in arms)


def _fields_of(cls: type[Any]) -> dict[str, tuple[Any, str | None]]:
    """Return a model's or dataclass's fields: each one's type and serialization alias, by attribute name."""
    if issubclass(cls, BaseModel):
        return {name: (info.annotation, info.serialization_alias) for name, info in cls.model_fields.items()}
    hints = get_type_hints(cls)
    return {field.name: (hints.get(field.name, Any), None) for field in dataclass_fields(cls)}


def _key(parameter: ParameterInfo, part: HttpxArgument) -> str:
    """Return the name a value is sent under: a query parameter's, header's, form field's, file's or JSON field's.

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


def _all_plain(annotation: Any) -> bool:
    """Return whether every type a value of ``annotation`` can have is plain; see ``_is_plain``."""
    return all(_is_plain(arm) for arm in _arms(annotation))


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


def _field_text(value: object) -> str | list[str]:
    """Return a spread field's JSON-ready value as text, or a list of texts for a list."""
    if isinstance(value, list):
        return [_to_text(item) for item in cast("list[object]", value)]
    return _to_text(value)


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
