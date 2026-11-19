"""Plan how an endpoint's calls become requests, when its class is defined.

``Endpoint.set_up_request`` calls ``plan_request`` with the endpoint's final
path template (any resource prefix joined on), its parameters, and whether it's
``async def``. It checks that they fit together, raising ``DefinitionError`` if
they don't, and returns the ``RequestPlan`` that ``_builder.build_request``
follows on each call. The planner decides everything, ``Send`` options
included, and bakes it into the plan, so the builder never reads annotations,
``Send`` or the specs.

Where each parameter goes is decided once, and never guessed:

1. A parameter that a path placeholder names fills it. It must be a plain value
   that can't be ``None``, with no helper but ``Url()``, and no ``Send``.
2. Every other parameter has a ``clientx.arguments`` helper in its outermost
   ``Annotated``, and goes to that helper's ``build_request`` argument. A
   parameter without one is an error, and so is a helper or ``Send`` anywhere
   else in its type, a default inside a helper, or a helper or ``Send`` on a
   model's field.

What each argument takes is an ``HttpxArgumentSpec`` subclass, one per
argument, so a rule that differs by argument lives in that argument's class:

- A plain value is on an allow-list: ``str``, ``int``, ``float``, ``bool``,
  ``Enum``, ``date``, ``datetime``, ``time``, ``UUID``, ``Decimal``, ``bytes``,
  a ``Literal`` of those, or a ``NewType`` of one. ``Any``, or no annotation,
  is the escape hatch.
- The query string and the form take a plain value, or a collection of them,
  which repeats the key; headers take a plain value. A model, dataclass or
  mapping marked ``Query()``, ``Header()`` or ``Form()`` is spread into it, one
  value per field, and each field follows the same rule.
- A file is ``bytes``, a binary file, or a ``(filename, content[,
  content_type[, headers]])`` tuple, never ``str``. A collection of files
  repeats the field.
- The raw body, one ``Body()`` parameter, is ``str``, ``bytes``, or a stream of
  bytes that matches the client, sync or async.
- A JSON field takes any value. A lone ``Json()`` parameter that isn't a plain
  value is the whole body, unless it has ``Send(embed=True)``.
- A request has one kind of body: JSON, raw content, or a form of ``Form()``
  and ``File()`` parameters.
- Two values sent to one argument under one key raise; header keys compare
  case-insensitively. A spread mapping's keys exist only at the call, so a
  clash with one is the caller's to avoid.
- ``Send``'s dump options must fit the type, since pydantic ignores them
  silently otherwise: ``exclude_unset`` needs a pydantic model, and
  ``exclude_none`` and ``exclude_defaults`` a model or pydantic dataclass.

The path template has ``{name}``, filled with one segment, and ``{name:path}``,
whose value keeps its slashes. There are no literal braces: any brace that
isn't part of a placeholder raises.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterable, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from string import Formatter
from types import NoneType, UnionType
from typing import (
    IO,
    Any,
    ClassVar,
    Literal,
    TextIO,
    TypeAliasType,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)
from uuid import UUID

from pydantic import BaseModel
from pydantic.dataclasses import is_pydantic_dataclass
from pydantic_core import PydanticUndefined

from clientx._arguments import get_httpx_argument
from clientx._signature import NO_VALUE, ParameterInfo, unwrap_annotated
from clientx._types import HttpxArgument, Send
from clientx.exceptions import DefinitionError


# --- The plan -----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RequestPlan:
    """How a call's arguments become the request, worked out once per endpoint.

    The planner makes it when the class is defined; the builder follows it on
    each call.

    Attributes:
        path: The path template, split into text and placeholders, for the
            builder to fill in.
        parameters: The parameters sent under a key, and the ones spread
            into an argument, in signature order.
        body: The parameter that's the whole body, or ``None``: one
            ``Body()`` parameter, or a lone ``Json()`` one. Its ``key`` isn't
            used, and a ``None`` value means no body.
    """

    path: tuple[str | PathPlaceholder, ...]
    parameters: tuple[PlannedParameter | SpreadParameter, ...] = ()
    body: PlannedParameter | None = None


@dataclass(frozen=True, slots=True)
class DumpOptions:
    """Pydantic's dump options for a parameter's value, from its ``Send``.

    The planner sets them; the builder passes them to pydantic as they are,
    without reading ``Send``.
    """

    exclude_unset: bool = False
    exclude_none: bool = False
    exclude_defaults: bool = False


@dataclass(frozen=True, slots=True)
class PlannedParameter:
    """Where a parameter's value goes, and the key it's sent under.

    Attributes:
        name: The parameter's name, and its key in the call's arguments.
        httpx_argument: The ``build_request`` argument it goes to.
        key: The name it's sent under, such as the query parameter's.
        many: The value is a collection, sent as a repeated key.
        sends_null: A ``None`` passed explicitly is sent as ``null``. The
            planner sets it from the spec, so the builder needn't read one.
        dump: How pydantic dumps the value, for a model inside it.
    """

    name: str
    httpx_argument: HttpxArgument
    key: str
    many: bool = False
    sends_null: bool = False
    dump: DumpOptions = DumpOptions()


@dataclass(frozen=True, slots=True)
class SpreadParameter:
    """A model, dataclass or mapping parameter spread into a text argument.

    Attributes:
        name: The parameter's name, and its key in the call's arguments.
        httpx_argument: The ``build_request`` argument its fields go to.
        keys: Each field's attribute name, and the key it's sent under.
            ``None`` for a mapping, whose own keys exist only at the call and
            are sent as they are.
        dump: How pydantic dumps the value before its fields are sent.
    """

    name: str
    httpx_argument: HttpxArgument
    keys: tuple[tuple[str, str], ...] | None = None
    dump: DumpOptions = DumpOptions()


# --- Entry point --------------------------------------------------------------
def plan_request(path_template: str, parameters: Sequence[ParameterInfo], *, is_async: bool) -> RequestPlan:
    """Work out an endpoint's ``RequestPlan`` from its path and parameters.

    ``is_async`` says whether the endpoint is ``async def``, which is also
    whether its client is async, since each kind of endpoint goes on its own
    kind of client. A streamed body must match it.
    """
    path = _parse_path(path_template)
    path_placeholders = {part.name: part for part in path if isinstance(part, PathPlaceholder)}

    parameter_names = {parameter.name for parameter in parameters}
    for placeholder in path_placeholders.values():
        if placeholder.name not in parameter_names:
            raise DefinitionError(
                f"Path {path_template!r} has the placeholder {placeholder}, "
                f"but no parameter is named {placeholder.name!r}. "
                "Add the parameter, or remove the placeholder."
            )

    lone_body = _find_lone_body(parameters)
    body: PlannedParameter | None = None
    planned: list[PlannedParameter | SpreadParameter] = []
    for parameter in parameters:
        # First, so a nested helper gets its own message rather than "needs a
        # helper": ParameterInfo only reads the outermost Annotated.
        _check_nested(parameter)
        _check_helper_default(parameter)
        _check_model_fields(parameter)
        placeholder = path_placeholders.get(parameter.name)
        if placeholder is not None:
            _check_path_parameter(parameter, placeholder, path_template)
            continue
        argument = _helper_argument(parameter, path_template)
        if parameter is lone_body or _SPECS[argument].whole_body:
            body = _plan_body(parameter, argument, is_async=is_async)
        else:
            planned.append(_plan_keyed(parameter, argument))

    # Then the parameters together.
    _check_one_body(parameters)
    _check_one_whole_body(parameters)
    _check_key_clashes(planned)
    return RequestPlan(path=path, parameters=tuple(planned), body=body)


# --- Specs: what each build_request argument takes ----------------------------
class HttpxArgumentSpec:
    """What one ``build_request`` argument takes. Subclass it per argument.

    The planner asks the spec rather than testing for particular arguments, so
    a rule that differs by argument is changed in that argument's class. Each
    subclass lists only what differs from the defaults here. The classes are
    used as they are, never instantiated.

    Attributes:
        argument: The argument the subclass describes.
        helper: The helper that sends a parameter there, as written, for
            messages: ``"Query()"``.
        accepts: Where it goes and what it takes, for messages: ``"the
            headers, which take a plain value"``.
        body_kind: The kind of body it makes, for the one-body check, or
            ``None`` if it isn't a body.
        send_options: The ``Send`` options it supports, by field name. Any
            other option set on its parameter raises.
        whole_body: A parameter going there is the whole of it, so there's
            at most one, and it isn't sent under a key.
        takes_text: Each value is sent as text under a key, and a model,
            dataclass or mapping is spread into it, one value per field.
        takes_lists: A collection of values repeats the key, as in
            ``?tag=a&tag=b``, or several files under one field.
        lone_is_body: The only parameter going to it is the whole body, if
            it isn't a plain value and doesn't have ``Send(embed=True)``.
        sends_null: A parameter passed explicitly as ``None`` is sent as
            ``null``; one that isn't passed is left out. Without it, ``None``
            is always left out.
        streams: An iterable value is streamed, so it must match the client:
            sync for a sync client, async for an async one.
    """

    argument: ClassVar[HttpxArgument]
    helper: ClassVar[str]
    accepts: ClassVar[str]
    body_kind: ClassVar[str | None] = None
    send_options: ClassVar[frozenset[str]] = frozenset()
    whole_body: ClassVar[bool] = False
    takes_text: ClassVar[bool] = False
    takes_lists: ClassVar[bool] = False
    lone_is_body: ClassVar[bool] = False
    sends_null: ClassVar[bool] = False
    streams: ClassVar[bool] = False

    @classmethod
    def key(cls, name: str, alias: str | None) -> str:
        """Return the key a value is sent under: the alias, or else the name."""
        return alias or name

    @classmethod
    def clash_key(cls, key: str) -> str:
        """Return the form of a key that's compared to find clashes: as is."""
        return key

    @classmethod
    def takes_value(cls, annotation: Any) -> bool:
        """Return whether one value of this type can go there: a plain value.

        It takes one type, not a union: the planner splits one first.
        """
        return _is_plain(annotation)

    @classmethod
    def what_fits(cls) -> str:
        """Return what a value can be, for messages: a plain value."""
        plain_names = ", ".join(plain_type.__name__ for plain_type in _PLAIN_TYPES)
        return (
            f"A plain value is one of {plain_names}, or Any. For another type, annotate the parameter as str "
            "and convert the value at the call."
        )


class UrlSpec(HttpxArgumentSpec):
    argument = HttpxArgument.URL
    helper = "Url()"
    accepts = "the path, which takes a plain value"


class ParamsSpec(HttpxArgumentSpec):
    argument = HttpxArgument.PARAMS
    helper = "Query()"
    accepts = "the query string, which takes a plain value or a collection of them"
    takes_text = True
    takes_lists = True
    # For a spread model. Not exclude_none: a query string leaves out None.
    send_options = frozenset({"exclude_unset", "exclude_defaults"})


class HeadersSpec(HttpxArgumentSpec):
    argument = HttpxArgument.HEADERS
    helper = "Header()"
    accepts = "the headers, which take a plain value"
    takes_text = True
    # For a spread model. Not exclude_none: headers leave out None.
    send_options = frozenset({"exclude_unset", "exclude_defaults"})

    @classmethod
    def key(cls, name: str, alias: str | None) -> str:
        # Python names can't have "-", so request_id is sent as request-id, as
        # FastAPI's Header() does. An alias is sent as written.
        return alias or name.replace("_", "-")

    @classmethod
    def clash_key(cls, key: str) -> str:
        # Header names are case-insensitive in HTTP: X-Trace is x-trace.
        return key.lower()


class DataSpec(HttpxArgumentSpec):
    argument = HttpxArgument.DATA
    helper = "Form()"
    accepts = "the form, which takes a plain value or a collection of them"
    takes_text = True
    takes_lists = True
    body_kind = "a form"
    # For a spread model. Not exclude_none: a form leaves out None.
    send_options = frozenset({"exclude_unset", "exclude_defaults"})


class FilesSpec(HttpxArgumentSpec):
    argument = HttpxArgument.FILES
    helper = "File()"
    accepts = "the form's files, which take a file or a collection of them"
    body_kind = "a form"
    # Several files under one field, as from <input type="file" multiple>.
    takes_lists = True

    @classmethod
    def takes_value(cls, annotation: Any) -> bool:
        return _is_file(annotation)

    @classmethod
    def what_fits(cls) -> str:
        return (
            'A file is bytes, a binary file such as open(path, "rb"), or a (filename, content[, content_type[, '
            "headers]]) tuple, or Any. Pass text as bytes, with text.encode(), and open a path yourself."
        )


class ContentSpec(HttpxArgumentSpec):
    argument = HttpxArgument.CONTENT
    helper = "Body()"
    accepts = "the raw body"
    body_kind = "raw content"
    # A Body() parameter is the whole raw body, so there's one.
    whole_body = True
    # httpx2 streams an iterable body: a sync Client takes only a sync one, and
    # an AsyncClient only an async one.
    streams = True

    @classmethod
    def takes_value(cls, annotation: Any) -> bool:
        return _is_content(annotation)

    @classmethod
    def what_fits(cls) -> str:
        return "The raw body is str, bytes, or an iterable or async iterable of bytes, or Any."


class JsonSpec(HttpxArgumentSpec):
    argument = HttpxArgument.JSON
    helper = "Json()"
    accepts = "the JSON body"
    body_kind = "JSON"
    # A lone model is the body, {"name": ...}, as in FastAPI; Send(embed=True)
    # sends it under its name instead, {"user": {"name": ...}}.
    lone_is_body = True
    send_options = frozenset({"embed", "exclude_unset", "exclude_none", "exclude_defaults"})
    # JSON has null: update(nickname=None) sends {"nickname": null}, to clear
    # it. Query strings, headers and forms have no null.
    sends_null = True

    @classmethod
    def takes_value(cls, annotation: Any) -> bool:
        # Pydantic serializes any value, so a JSON field takes anything.
        return True

    @classmethod
    def what_fits(cls) -> str:
        return "Any value pydantic can serialize fits."


# Each argument a helper can mark, to its spec. COOKIES has no helper.
_SPECS: dict[HttpxArgument, type[HttpxArgumentSpec]] = {
    spec.argument: spec for spec in (UrlSpec, ParamsSpec, HeadersSpec, DataSpec, FilesSpec, ContentSpec, JsonSpec)
}


# --- The path -----------------------------------------------------------------
_PATH_SYNTAX = (
    "A placeholder is {name}, for one path segment, or {name:path}, for a value that keeps its "
    "slashes, where name is a parameter's name."
)


def _check_path_parameter(parameter: ParameterInfo, placeholder: PathPlaceholder, path_template: str) -> None:
    """Raise ``DefinitionError`` if a parameter can't fill its placeholder.

    It must be a plain value that can't be ``None``, with no helper but
    ``Url()``, and no ``Send``.
    """
    fills = f"Parameter {parameter.name!r} fills {placeholder} in the path {path_template!r}"
    argument = parameter.httpx_argument
    if argument is not None and argument is not HttpxArgument.URL:
        raise DefinitionError(
            f"{fills}, so it can't also be marked {_SPECS[argument].helper}. "
            "Remove its helper, or rename the parameter or the placeholder."
        )
    if _allows_none(parameter.annotation):
        raise DefinitionError(
            f"{fills}, so it can't be None: a None value would always fail at the call. Remove None from its type."
        )
    if not all(UrlSpec.takes_value(arm) for arm in _arms(parameter.annotation)):
        raise DefinitionError(f"{fills}, so it must be a plain value. {UrlSpec.what_fits()}")
    if parameter.send != Send():
        raise DefinitionError(f"{fills}, so Send doesn't apply to it. Remove it.")


@dataclass(frozen=True)
class PathPlaceholder:
    """A ``{name}`` slot in the path template.

    Attributes:
        keep_slashes: ``{name:path}`` was written, so the builder sends any
            ``/`` in the value as it is, rather than encoding it as ``%2F``.
    """

    name: str
    keep_slashes: bool = False

    def __str__(self) -> str:
        return f"{{{self.name}:path}}" if self.keep_slashes else f"{{{self.name}}}"


def _parse_path(path_template: str) -> tuple[str | PathPlaceholder, ...]:
    """Split a path template into text and placeholders, in order."""
    # Formatter().parse splits "/user/{user_id}" into (text, name, spec,
    # conversion) chunks: ("/user/", "user_id", "", None).
    # parse() is lazy, so list() makes it raise here, inside the try, rather
    # than partway through the loop.
    try:
        chunks = list(Formatter().parse(path_template))
    except ValueError as error:
        raise DefinitionError(
            f"Path {path_template!r} has a brace that isn't part of a placeholder. {_PATH_SYNTAX}"
        ) from error

    parts: list[str | PathPlaceholder] = []
    for text, name, spec, conversion in chunks:
        # Formatter turns {{ and }} into a brace in the text. ClientX has no
        # literal braces, so any brace there is a mistake.
        if "{" in text or "}" in text:
            raise DefinitionError(
                f"Path {path_template!r} has a brace that isn't part of a placeholder. {_PATH_SYNTAX}"
            )
        if text:
            parts.append(text)
        if name is None:
            continue
        _check_placeholder(path_template, name, spec, conversion)
        parts.append(PathPlaceholder(name, keep_slashes=spec == "path"))
    return tuple(parts)


def _check_placeholder(path_template: str, name: str, spec: str | None, conversion: str | None) -> None:
    """Raise ``DefinitionError`` unless it's ``{name}`` or ``{name:path}``.

    ``Formatter`` only checks the braces, so ``{user-id}``, ``{a.b}``,
    ``{c[0]}``, ``{}``, ``{d!r}`` and ``{e:int}`` all reach here.
    """
    if name.isidentifier() and conversion is None and spec in {"", "path"}:
        return
    # Rebuild the placeholder as it was written, for the message.
    written = "{" + name + (f"!{conversion}" if conversion else "") + (f":{spec}" if spec else "") + "}"
    raise DefinitionError(f"Path {path_template!r}: ClientX can't fill the placeholder {written}. {_PATH_SYNTAX}")


# --- Parameters outside the path ----------------------------------------------
def _helper_argument(parameter: ParameterInfo, path_template: str) -> HttpxArgument:
    """Return the argument a parameter outside the path goes to: its helper's.

    It needs a helper that says where it goes, ``Url()`` only fits a parameter
    that fills a placeholder, each ``Send`` option must be in its spec's
    ``send_options``, and a dump option must fit the type. An option set to
    ``False`` counts too: it can't apply there either.

    Raises:
        DefinitionError: If any of those doesn't hold.
    """
    argument = parameter.httpx_argument
    if argument is None:
        raise DefinitionError(
            f"Parameter {parameter.name!r} needs a helper that says where it goes: Query(), Header(), "
            f"Json(), Body(), Form() or File(), as in {_example(parameter)}. Only a parameter named like a path "
            "placeholder goes without one."
        )
    if argument is HttpxArgument.URL:
        raise DefinitionError(
            f"Parameter {parameter.name!r} is marked Url(), but the path {path_template!r} has no "
            f"placeholder {{{parameter.name}}}. Add the placeholder, or remove Url()."
        )
    # Each Send option that's set must be one the argument's spec supports.
    spec = _SPECS[argument]
    for option in fields(Send):
        if getattr(parameter.send, option.name) is None or option.name in spec.send_options:
            continue
        helpers = [s.helper for s in _SPECS.values() if option.name in s.send_options]
        supported_by = helpers[0] if len(helpers) == 1 else f"{', '.join(helpers[:-1])} or {helpers[-1]}"
        raise DefinitionError(
            f"Parameter {parameter.name!r} has Send({option.name}=...), which applies only to a "
            f"{supported_by} parameter, but it's marked {spec.helper}. Remove it."
        )
    _check_dump_options(parameter)
    return argument


def _example(parameter: ParameterInfo) -> str:
    """Return the parameter with the helper it most likely needs, for a message.

    That's ``Query()`` for a plain value and ``Json()`` for anything else.
    """
    if parameter.annotation is NO_VALUE:
        return f"{parameter.name}: Annotated[str, Query()]"
    base = parameter.base_type
    type_text = base.__qualname__ if isinstance(base, type) else repr(base)
    helper = "Query()" if _all_plain(parameter.annotation) else "Json()"
    return f"{parameter.name}: Annotated[{type_text}, {helper}]"


# --- Send's dump options ------------------------------------------------------
_PYDANTIC_CLASS = (
    "a pydantic model or pydantic dataclass (pydantic doesn't apply it to a stdlib dataclass: make it a "
    "pydantic.dataclasses.dataclass)"
)


def _is_model(cls: type[Any]) -> bool:
    return issubclass(cls, BaseModel)


def _is_model_or_pydantic_dataclass(cls: type[Any]) -> bool:
    return issubclass(cls, BaseModel) or is_pydantic_dataclass(cls)


# Each Send dump option, the classes whose fields it affects, and those in
# words, for messages. Dumping a value by its own type, pydantic silently
# ignores all three on a stdlib dataclass and a dict, and exclude_unset on a
# pydantic dataclass too, which doesn't record which fields were set; so an
# option on a type it can't affect raises instead.
_DUMP_OPTIONS: dict[str, tuple[Callable[[type[Any]], bool], str]] = {
    "exclude_unset": (_is_model, "a pydantic model, the only kind that records which fields were set"),
    "exclude_none": (_is_model_or_pydantic_dataclass, _PYDANTIC_CLASS),
    "exclude_defaults": (_is_model_or_pydantic_dataclass, _PYDANTIC_CLASS),
}


def _check_dump_options(parameter: ParameterInfo) -> None:
    """Raise ``DefinitionError`` for a dump option the type can't use.

    Each affects the fields of some classes only (``_DUMP_OPTIONS``), so the
    parameter's type must have one, at any depth: ``list[User]`` counts.
    """
    for option, (affects, described) in _DUMP_OPTIONS.items():
        if getattr(parameter.send, option) is None:
            continue
        if not _contains_class(parameter.annotation, affects, frozenset()):
            raise DefinitionError(
                f"Parameter {parameter.name!r} has Send({option}=...), which leaves out fields of "
                f"{described}, but its type has none. Remove it."
            )


def _dump_options(parameter: ParameterInfo) -> DumpOptions:
    """Return the parameter's ``Send`` dump options, for the plan."""
    send = parameter.send
    return DumpOptions(
        exclude_unset=bool(send.exclude_unset),
        exclude_none=bool(send.exclude_none),
        exclude_defaults=bool(send.exclude_defaults),
    )


def _contains_class(annotation: Any, wanted: Callable[[type[Any]], bool], seen: frozenset[TypeAliasType]) -> bool:
    """Return whether ``annotation``, or a type inside it, is a wanted class.

    ``seen`` holds the ``type`` aliases already expanded, as in ``_contains``,
    so one that contains itself is expanded only once.
    """
    alias = annotation if isinstance(annotation, TypeAliasType) else get_origin(annotation)
    if isinstance(alias, TypeAliasType):
        if alias in seen:
            return False
        seen |= {alias}
    base, _ = unwrap_annotated(annotation)
    cls = _class_of(base)
    if cls is not None and wanted(cls):
        return True
    return any(_contains_class(arg, wanted, seen) for arg in get_args(base))


# nested helpers and Send
def _check_nested(parameter: ParameterInfo) -> None:
    """Raise ``DefinitionError`` if a helper or ``Send`` is inside the type.

    ClientX reads both only in the outermost ``Annotated``, so the helper in
    ``Annotated[str, Header()] | None`` would be ignored.
    """
    # base_type is the type without the outermost Annotated, which
    # ParameterInfo has already read, so only what's inside it is searched.
    inside = get_args(parameter.base_type)
    if any(_contains(arg, _is_helper, frozenset()) for arg in inside):
        raise DefinitionError(
            f"Parameter {parameter.name!r} has a helper inside its type. ClientX reads a helper only "
            "in the outermost Annotated, so move it there: for example, Annotated[str | None, Header()] "
            "rather than Annotated[str, Header()] | None."
        )
    if any(_contains(arg, _is_send, frozenset()) for arg in inside):
        raise DefinitionError(
            f"Parameter {parameter.name!r} has a Send inside its type. ClientX reads Send only in the "
            "outermost Annotated, so move it there: for example, Annotated[list[str] | None, Json(), "
            "Send(embed=True)] rather than Annotated[list[str], Json(), Send(embed=True)] | None."
        )


# nested helpers and Send
def _contains(annotation: Any, wanted: Callable[[object], bool], seen: frozenset[TypeAliasType]) -> bool:
    """Return whether ``annotation``, or a type inside it, has ``wanted``.

    ``seen`` holds the ``type`` aliases already expanded on the way here, so one
    that contains itself, such as ``type Value = dict[str, Value] | str``, is
    expanded only once.
    """
    alias = annotation if isinstance(annotation, TypeAliasType) else get_origin(annotation)
    if isinstance(alias, TypeAliasType):
        if alias in seen:
            return False
        seen |= {alias}
    # unwrap_annotated expands a type alias too, so metadata inside one counts.
    base, metadata = unwrap_annotated(annotation)
    if any(wanted(meta) for meta in metadata):
        return True
    return any(_contains(arg, wanted, seen) for arg in get_args(base))


# nested helpers and Send
def _is_helper(meta: object) -> bool:
    return get_httpx_argument(meta) is not None


# nested helpers and Send
def _is_send(meta: object) -> bool:
    return isinstance(meta, Send)


# --- Defaults inside a helper -------------------------------------------------
def _check_helper_default(parameter: ParameterInfo) -> None:
    """Raise ``DefinitionError`` if the helper has a default.

    The helpers take ``pydantic.Field``'s arguments, so ``Query(1)``,
    ``Query(default=1)`` and ``Query(default_factory=list)`` all set one, but
    ClientX reads the default after ``=``, as Python does.
    """
    field_info = parameter.clientx_field_info
    if field_info is None:
        return
    if field_info.default is not PydanticUndefined or field_info.default_factory is not None:
        raise DefinitionError(
            f"Parameter {parameter.name!r} has a default inside its helper, where ClientX doesn't read it. "
            "Put the default after = instead, as in page: Annotated[int, Query()] = 1."
        )


# --- Helpers and Send on a model's fields -------------------------------------
def _check_model_fields(parameter: ParameterInfo) -> None:
    """Raise ``DefinitionError`` if a model's field has a helper or ``Send``.

    The parameter's helper decides where the whole model goes, so ClientX
    doesn't read either on a field. Each arm of a union is checked, so
    ``Filters | None`` counts.
    """
    for arm in _arms(parameter.annotation):
        cls = _class_of(arm)
        if cls is None or not issubclass(cls, BaseModel):
            continue
        for field_name, field_info in cls.model_fields.items():
            if _is_helper(field_info):
                raise DefinitionError(
                    f"Field {field_name!r} of {cls.__name__} has a clientx.arguments helper, but ClientX reads "
                    f"helpers only on endpoint parameters. Put the helper on parameter {parameter.name!r} "
                    f"instead, as in Annotated[{cls.__name__}, Query()]: all of the model's fields then go there."
                )
            if any(_is_send(meta) for meta in field_info.metadata):
                raise DefinitionError(
                    f"Field {field_name!r} of {cls.__name__} has a Send, but ClientX reads Send only on "
                    f"endpoint parameters. Put it on parameter {parameter.name!r} instead."
                )


# --- Parameters sent under a key ----------------------------------------------
def _plan_keyed(parameter: ParameterInfo, argument: HttpxArgument) -> PlannedParameter | SpreadParameter:
    """Return where a parameter sent under a key goes, and its key.

    A value the argument's spec takes is sent once; a collection of them
    repeats the key, if the spec ``takes_lists``; a model, dataclass or mapping
    is spread, one value per field or item, if the spec ``takes_text``.
    Anything else raises ``DefinitionError``, saying what fits.
    """
    spec = _SPECS[argument]
    field_info = parameter.clientx_field_info
    alias = field_info.serialization_alias if field_info is not None else None
    key = spec.key(parameter.name, alias)
    dump = _dump_options(parameter)
    # Send(exclude_none=True) leaves out None, so it isn't sent as null.
    sends_null = spec.sends_null and not dump.exclude_none
    arms = _arms(parameter.annotation)
    if all(spec.takes_value(arm) for arm in arms):
        return PlannedParameter(parameter.name, argument, key, sends_null=sends_null, dump=dump)
    if spec.takes_lists and all(_is_list_of(arm, spec.takes_value) for arm in arms):
        return PlannedParameter(parameter.name, argument, key, many=True)
    if spec.takes_text and len(arms) == 1 and _has_fields(arms[0]):
        return _plan_spread(parameter, argument, arms[0])
    raise DefinitionError(
        f"Parameter {parameter.name!r} is marked {spec.helper}, so it goes to {spec.accepts}. {spec.what_fits()}"
    )


def _plan_spread(parameter: ParameterInfo, argument: HttpxArgument, annotation: Any) -> SpreadParameter:
    """Plan a model, dataclass or mapping parameter spread into ``argument``.

    Each field is sent under the key the argument's spec gives its alias or
    attribute name, so a header field's ``_`` becomes ``-`` too. A mapping's
    items are sent under their own keys, as they are. Each field, or the
    mapping's value type, must be something the argument takes, as a parameter
    must, so a nested model raises ``DefinitionError``.
    """
    spec = _SPECS[argument]
    cls = cast("type[Any]", _class_of(annotation))
    if issubclass(cls, Mapping):
        # dict[str, int] lists the key and value types; a bare dict, neither.
        type_args = get_args(annotation)
        value_type = type_args[1] if len(type_args) == 2 else Any
        if not _fits(value_type, spec):
            raise DefinitionError(
                f"Parameter {parameter.name!r} is marked {spec.helper}, so each item of the mapping goes to "
                f"{spec.accepts}. Its value type isn't one."
            )
        return SpreadParameter(parameter.name, argument)
    keys: list[tuple[str, str]] = []
    for attribute, (field_type, alias) in _fields_of(cls).items():
        if not _fits(field_type, spec):
            raise DefinitionError(
                f"Parameter {parameter.name!r} is marked {spec.helper}, so each field of {cls.__name__} goes to "
                f"{spec.accepts}. Field {attribute!r} isn't one."
            )
        keys.append((attribute, spec.key(attribute, alias)))
    return SpreadParameter(parameter.name, argument, tuple(keys), dump=_dump_options(parameter))


def _fields_of(cls: type[Any]) -> dict[str, tuple[Any, str | None]]:
    """Return each field's type and serialization alias, by attribute name."""
    if issubclass(cls, BaseModel):
        return {name: (info.annotation, info.serialization_alias) for name, info in cls.model_fields.items()}
    # A dataclass: its fields have no aliases.
    hints = get_type_hints(cls)
    return {field.name: (hints.get(field.name, Any), None) for field in fields(cls)}


def _fits(annotation: Any, spec: type[HttpxArgumentSpec]) -> bool:
    """Return whether a value of this type can go to the spec's argument.

    That's a value the spec takes, or a collection of them if it
    ``takes_lists``.
    """
    arms = _arms(annotation)
    if all(spec.takes_value(arm) for arm in arms):
        return True
    return spec.takes_lists and all(_is_list_of(arm, spec.takes_value) for arm in arms)


def _check_key_clashes(planned: Sequence[PlannedParameter | SpreadParameter]) -> None:
    """Raise ``DefinitionError`` if two values go to one argument under one key.

    httpx2 would keep only one of them, silently. Only keys known now count: a
    mapping's keys exist only at the call, so a clash with one is the caller's
    to avoid.
    """
    # Each (argument, clash key) seen so far, to where it came from and its key.
    sources: dict[tuple[HttpxArgument, str], tuple[str, str]] = {}
    for item in planned:
        if isinstance(item, PlannedParameter):
            keyed = [(item.key, f"parameter {item.name!r}")]
        elif item.keys is not None:
            keyed = [(key, f"field {attribute!r} of parameter {item.name!r}") for attribute, key in item.keys]
        else:
            continue
        spec = _SPECS[item.httpx_argument]
        for key, source in keyed:
            where = (item.httpx_argument, spec.clash_key(key))
            if where not in sources:
                sources[where] = (source, key)
                continue
            earlier_source, earlier_key = sources[where]
            sent_as = f"both sent as {key!r}" if key == earlier_key else f"sent as {earlier_key!r} and {key!r}"
            raise DefinitionError(
                f"{earlier_source.capitalize()} and {source} are {sent_as} by {spec.helper}, the same key, so "
                "one would be lost. Rename one, or give it an alias."
            )


# --- The body -----------------------------------------------------------------
def _find_lone_body(parameters: Sequence[ParameterInfo]) -> ParameterInfo | None:
    """Return the parameter that's the whole body by the lone rule, or ``None``.

    That's the only parameter going to an argument whose spec has
    ``lone_is_body`` (JSON), unless it's a plain value or has
    ``Send(embed=True)``: those are sent under their name, as FastAPI does. So
    adding a second ``Json()`` parameter moves the first under its name.
    """
    candidates = [p for p in parameters if p.httpx_argument is not None and _SPECS[p.httpx_argument].lone_is_body]
    if len(candidates) != 1:
        return None
    (parameter,) = candidates
    if parameter.send.embed or _all_plain(parameter.annotation):
        return None
    return parameter


def _plan_body(parameter: ParameterInfo, argument: HttpxArgument, *, is_async: bool) -> PlannedParameter:
    """Plan a parameter that's the whole body: ``Body()``, or a lone ``Json()``.

    Its value must be one the argument's spec takes, and a stream must match
    the client, or ``DefinitionError`` is raised. ``None`` means no body, never
    ``null``, for JSON too: an API that takes an object rarely wants the body
    ``null``.
    """
    spec = _SPECS[argument]
    if not all(spec.takes_value(arm) for arm in _arms(parameter.annotation)):
        raise DefinitionError(
            f"Parameter {parameter.name!r} is marked {spec.helper}, so it goes to {spec.accepts}. {spec.what_fits()}"
        )
    if spec.streams:
        _check_stream_kind(parameter, spec, is_async=is_async)
    # The key isn't used: the value is the whole body.
    return PlannedParameter(parameter.name, argument, key=parameter.name, dump=_dump_options(parameter))


def _check_stream_kind(parameter: ParameterInfo, spec: type[HttpxArgumentSpec], *, is_async: bool) -> None:
    """Raise ``DefinitionError`` if a streamed body doesn't match the client.

    httpx2 raises ``RuntimeError`` at the call otherwise: a sync ``Client``
    can't send an async iterable, and an ``AsyncClient`` can't send a sync one,
    a ``list[bytes]`` included. ``str``, ``bytes`` and ``Any`` fit both.
    """
    for arm in _arms(parameter.annotation):
        cls = _class_of(arm)
        if cls is None or issubclass(cls, str | bytes):
            continue
        if is_async and issubclass(cls, Iterable):
            raise DefinitionError(
                f"Parameter {parameter.name!r} is marked {spec.helper} with a sync iterable, but the endpoint is "
                "async, and an async client streams only an async iterable of bytes. Make it an "
                "AsyncIterator[bytes], or bytes."
            )
        if not is_async and issubclass(cls, AsyncIterable):
            raise DefinitionError(
                f"Parameter {parameter.name!r} is marked {spec.helper} with an async iterable, but the endpoint is "
                "sync, and a sync client streams only an iterable of bytes. Make it an Iterator[bytes], or bytes, "
                "or move the endpoint to an AsyncClientX."
            )


def _check_one_body(parameters: Sequence[ParameterInfo]) -> None:
    """Raise ``DefinitionError`` if the parameters mix kinds of body.

    httpx2 sends one body, and given several, it silently drops the others.
    """
    body_parameters: list[tuple[str, str]] = []
    for parameter in parameters:
        if parameter.httpx_argument is None:  # A path parameter without Url().
            continue
        kind = _SPECS[parameter.httpx_argument].body_kind
        if kind is not None:
            body_parameters.append((parameter.name, kind))
    if len({kind for _, kind in body_parameters}) > 1:
        listed = ", ".join(f"{name!r} ({kind})" for name, kind in body_parameters)
        raise DefinitionError(
            f"The parameters make more than one kind of body: {listed}. A request has one body: JSON, "
            "the raw content of one Body() parameter, or a form of Form() and File() parameters."
        )


def _check_one_whole_body(parameters: Sequence[ParameterInfo]) -> None:
    """Raise ``DefinitionError`` if two parameters go where only one can.

    That's an argument whose spec has ``whole_body``, such as ``content``: a
    ``Body()`` parameter is the whole raw body.
    """
    names_by_argument: dict[HttpxArgument, list[str]] = {}
    for parameter in parameters:
        if parameter.httpx_argument is not None and _SPECS[parameter.httpx_argument].whole_body:
            names_by_argument.setdefault(parameter.httpx_argument, []).append(repr(parameter.name))
    for argument, names in names_by_argument.items():
        if len(names) > 1:
            raise DefinitionError(
                f"Parameters {', '.join(names)} are all marked {_SPECS[argument].helper}, but an endpoint "
                "can have only one."
            )


# --- What a type is -----------------------------------------------------------
# The plain-value allow-list: each has one defined text form. A subclass counts
# too, so bool (an int), datetime (a date) and any Enum are in.
_PLAIN_TYPES = (str, int, float, bool, Enum, date, datetime, time, UUID, Decimal, bytes)


def _is_plain(annotation: Any) -> bool:
    """Return whether a value of this type is sent as one piece of text.

    It is if it's on the allow-list (a ``NewType`` of one counts), a
    ``Literal`` of values on it, or ``Any`` or no annotation, the escape hatch.
    It takes one type: ``_all_plain`` splits a union first.
    """
    if annotation is Any or annotation is NO_VALUE:
        return True
    if get_origin(annotation) is Literal:
        # Literal["asc", "desc"]: each value is plain. None is left out.
        return all(value is None or isinstance(value, _PLAIN_TYPES) for value in get_args(annotation))
    cls = _class_of(annotation)
    return cls is not None and issubclass(cls, _PLAIN_TYPES)


# How deep _arms follows unions inside unions, so a type alias that contains
# itself, such as ``type U = int | U``, can't recurse forever.
_MAX_UNION_DEPTH = 100


def _arms(annotation: Any, depth: int = 0) -> list[Any]:
    """Return the types a value of ``annotation`` can have, without ``None``.

    For a union, they're its members, each without ``Annotated`` or a ``type``
    alias, and a union inside a union is flattened: ``int | (str | None)`` gives
    ``[int, str]``. A type that isn't a union is the only one.
    """
    base, _ = unwrap_annotated(annotation)
    if base is NoneType:
        return []
    # Union is Optional[int] and Union[int, str]; UnionType is int | str.
    if get_origin(base) not in {Union, UnionType} or depth > _MAX_UNION_DEPTH:
        return [base]
    return [arm for member in get_args(base) for arm in _arms(member, depth + 1)]


def _all_plain(annotation: Any) -> bool:
    return all(_is_plain(arm) for arm in _arms(annotation))


def _allows_none(annotation: Any, depth: int = 0) -> bool:
    """Return whether ``None`` is one of the types a value can have.

    ``_arms`` drops ``None``, so this is how to ask about it: ``int | None``
    and ``Optional[int]`` allow it.
    """
    base, _ = unwrap_annotated(annotation)
    if base is NoneType or base is None:
        return True
    if get_origin(base) not in {Union, UnionType} or depth > _MAX_UNION_DEPTH:
        return False
    return any(_allows_none(member, depth + 1) for member in get_args(base))


def _class_of(annotation: Any) -> type[Any] | None:
    """Return the class a type stands for, or ``None`` if it isn't one.

    ``list[str]`` stands for ``list``, and ``NewType("UserId", int)`` for
    ``int``. ``Literal["a"]`` and a ``TypeVar``, for example, aren't classes.
    """
    # A NewType isn't a class; the type it's made from is.
    while hasattr(annotation, "__supertype__"):
        annotation = annotation.__supertype__
    # get_origin gives list for list[str], and None for a plain class like int.
    cls: object = get_origin(annotation) or annotation
    return cast("type[Any]", cls) if isinstance(cls, type) else None


def _has_fields(annotation: Any) -> bool:
    """Return whether the type is a model, dataclass or mapping: has fields."""
    cls = _class_of(annotation)
    return cls is not None and (issubclass(cls, BaseModel | Mapping) or is_dataclass(cls))


def _is_list_of(annotation: Any, takes_value: Callable[[Any], bool]) -> bool:
    """Return whether the type is a collection of values ``takes_value`` takes.

    Any collection but a mapping counts: ``list``, ``tuple``, ``set`` and
    ``frozenset``. A set's order can change from run to run, and the request
    with it. ``str``, ``bytes`` and
    ``bytearray`` are collections too, but of characters and numbers, not of
    values, so they don't count.
    """
    cls = _class_of(annotation)
    if cls is None or issubclass(cls, str | bytes | bytearray | Mapping) or not issubclass(cls, Collection):
        return False
    # tuple[str, ...] lists str and then Ellipsis. A bare list has no item
    # types, so its items count as Any.
    item_types = [item for item in get_args(annotation) if item is not Ellipsis]
    return all(takes_value(arm) for item in item_types for arm in _arms(item))


def _is_file(annotation: Any) -> bool:
    """Return whether a value of this type is one file httpx2 can send.

    That's file content (``bytes`` or a binary file), a ``(filename,
    content[, content_type[, headers]])`` tuple, or ``Any``. Not ``str``:
    httpx2 would send the string as the file's content, so ``"report.pdf"``
    would upload that text, named ``upload``.
    """
    cls = _class_of(annotation)
    if cls is not None and issubclass(cls, tuple):
        return _is_file_tuple(annotation)
    return _is_file_content(annotation)


def _is_file_content(annotation: Any) -> bool:
    """Return whether the type is ``bytes``, a binary file, or ``Any``."""
    if annotation is Any or annotation is NO_VALUE:
        return True
    cls = _class_of(annotation)
    return cls is not None and (issubclass(cls, bytes) or _is_binary_file(annotation))


def _is_binary_file(annotation: Any) -> bool:
    """Return whether the type is a file opened for bytes.

    ``IO[bytes]`` and ``BinaryIO`` are; so are ``io.BytesIO`` and what
    ``open(path, "rb")`` returns. ``IO[str]``, ``TextIO`` and a text file
    aren't. A bare ``IO`` has no item type, so it counts as ``Any``.
    """
    cls = _class_of(annotation)
    if cls is None:
        return False
    if issubclass(cls, IO):
        type_args = get_args(annotation)
        return not issubclass(cls, TextIO) and (not type_args or type_args[0] is bytes or type_args[0] is Any)
    return issubclass(cls, io.RawIOBase | io.BufferedIOBase)


def _is_file_tuple(annotation: Any) -> bool:
    """Return whether the type is ``(filename, content[, type[, headers]])``.

    The filename and content type are ``str`` or ``None``; the content is file
    content; the headers, the file part's own, a mapping of ``str`` to
    ``str``. A bare ``tuple`` has no item types, so it counts as ``Any``.
    """
    type_args = get_args(annotation)
    if not type_args:
        return True
    if len(type_args) not in {2, 3, 4} or Ellipsis in type_args:
        return False
    filename, content, *rest = type_args
    content_arms = _arms(content)
    return (
        _is_text_or_none(filename)
        and bool(content_arms)
        and all(_is_file_content(arm) for arm in content_arms)
        and all(_is_text_or_none(item) for item in rest[:1])
        and all(_is_text_mapping(item) for item in rest[1:])
    )


def _is_text_mapping(annotation: Any) -> bool:
    """Return whether the type is a mapping of ``str`` to ``str``, or ``Any``.

    A bare ``Mapping`` or ``dict`` has no item types, so it counts as ``Any``.
    """
    arms = _arms(annotation)
    for arm in arms:
        if arm is Any:
            continue
        cls = _class_of(arm)
        if cls is None or not issubclass(cls, Mapping):
            return False
        if not all(_is_text_or_none(item) for item in get_args(arm)):
            return False
    return bool(arms)


def _is_text_or_none(annotation: Any) -> bool:
    """Return whether the type is ``str``, ``None``, both, or ``Any``."""
    return all(arm is Any or (isinstance(arm, type) and issubclass(arm, str)) for arm in _arms(annotation))


def _is_content(annotation: Any) -> bool:
    """Return whether a value of this type is a raw body httpx2 can send.

    That's ``str`` (sent as UTF-8), ``bytes``, or an iterable or async
    iterable of bytes, which is streamed; or ``Any``. A model, mapping,
    ``bytearray`` or ``memoryview`` is iterable too, but not of bytes.
    """
    if annotation is Any or annotation is NO_VALUE:
        return True
    cls = _class_of(annotation)
    if cls is None:
        return False
    if issubclass(cls, str | bytes):
        return True
    if issubclass(cls, BaseModel | Mapping | bytearray | memoryview) or not issubclass(cls, Iterable | AsyncIterable):
        return False
    # The item type comes first: Iterator[bytes], Generator[bytes, None, None].
    # A bare Iterator has none, so its items count as Any.
    type_args = get_args(annotation)
    return not type_args or all(arm is Any or arm is bytes for arm in _arms(type_args[0]))
