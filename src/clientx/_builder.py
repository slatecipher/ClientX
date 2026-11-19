"""Build one call's request by the endpoint's ``RequestPlan``.

``Endpoint.request_arguments`` calls ``build_request`` with the plan
``_planner`` made when the class was defined, the call's arguments, and the
names the caller passed. The builder only follows the plan: it never reads
annotations, ``Send`` or the specs, and the only error it raises is
``ArgumentError``, before anything is sent, for a path value that would call a
different path, or a value that can't become text or JSON.

- Path: each placeholder is filled with percent-encoded text, one segment, or
  several for ``{name:path}``. ``.`` and ``..`` are encoded too. A ``None`` or
  empty value, or a ``{name:path}`` value with an empty segment, raises.
- Text: a value becomes text by one rule, for the path, query, headers and
  form: pydantic's JSON form, so an ``Enum`` is its value, a ``datetime`` ISO
  8601 text, a number or ``bool`` JSON text (``true``), and a list or dict
  JSON text. ``str`` is used only for an object pydantic doesn't know.
- Query, headers, form: ``None`` is left out, and so is an empty collection
  and a ``None`` item in one. Where the plan says ``many``, a collection
  repeats the key, decided by the value: a ``str`` is one value. A spread
  model or dataclass is dumped with its ``DumpOptions``, then each field is
  sent under its planned key; what a spread mapping, or a model with its own
  model serializer, dumps is sent under its own keys.
- Files: each file is passed as it is, and a list of them repeats the field.
  A ``None`` in the list is left out.
- JSON fields: each is dumped with its ``DumpOptions``, by alias, into one JSON
  object. ``None`` is left out, unless it was passed explicitly and the plan
  says ``sends_null``: then it's ``null``. With no fields left, there's no
  JSON body.
- Body: ``Body()`` is passed as it is; a lone JSON body is dumped with its
  ``DumpOptions``. ``None`` means no body, never ``null``.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Generator, Iterable, Mapping
from contextlib import contextmanager
from typing import Any, cast
from urllib.parse import quote

from pydantic import TypeAdapter
from pydantic_core import PydanticSerializationError, to_jsonable_python

from clientx._planner import DumpOptions, PathPlaceholder, PlannedParameter, RequestPlan, SpreadParameter
from clientx._types import BuildRequestKwargs, HttpxArgument
from clientx.exceptions import ArgumentError


# --- Entry point --------------------------------------------------------------
def build_request(
    plan: RequestPlan, arguments: Mapping[str, object], passed: Collection[str]
) -> tuple[str, BuildRequestKwargs]:
    """Return the URL path and the ``build_request`` arguments for one call.

    Args:
        plan: The endpoint's plan, from ``plan_request``.
        arguments: The call's arguments by parameter name, defaults filled in.
        passed: The names of the arguments the caller passed, so an explicit
            ``None`` can be told from a default one.

    Raises:
        ArgumentError: If a path value would change which path is called, or
            a value can't become text or JSON.
    """
    path = _build_path(plan.path, arguments)
    # Each argument's keyed values: params, headers, data and json. Files are a
    # list of pairs instead, so one field can repeat.
    keyed: dict[HttpxArgument, dict[str, object]] = {}
    files: list[tuple[str, object]] = []
    for item in plan.parameters:
        value = arguments[item.name]
        with _converting(item.name):
            if isinstance(item, SpreadParameter):
                if value is not None:
                    # A key known only at the call that equals another replaces
                    # it, as in dict.update; httpx2 sends both header names
                    # that differ only in case. The planner caught every clash
                    # it could see.
                    keyed.setdefault(item.httpx_argument, {}).update(_spread(item, value))
            elif item.httpx_argument is HttpxArgument.FILES:
                files.extend((item.key, file) for file in _files(item, value))
            elif (sent := _keyed_value(item, value, passed)) is not _LEFT_OUT:
                keyed.setdefault(item.httpx_argument, {})[item.key] = sent

    # Each argument's name is build_request's: "params", "headers", "data"...
    request_arguments: dict[str, object] = {argument.value: values for argument, values in keyed.items() if values}
    if files:
        request_arguments["files"] = files
    if plan.body is not None:
        request_arguments.update(_body(plan.body, arguments[plan.body.name]))
    return path, cast("BuildRequestKwargs", request_arguments)


# What _keyed_value returns for a value that isn't sent at all.
_LEFT_OUT = object()


def _keyed_value(item: PlannedParameter, value: object, passed: Collection[str]) -> object:
    """Return what's sent under a parameter's key, or ``_LEFT_OUT``.

    A JSON field is dumped, or is ``null`` for a ``None`` passed explicitly
    where the plan says ``sends_null``. Any other value becomes text. ``None``
    and an empty collection are left out.
    """
    if item.httpx_argument is HttpxArgument.JSON:
        if value is not None:
            return _dump_json(item, value)
        return None if item.sends_null and item.name in passed else _LEFT_OUT
    text = _text_value(value, many=item.many)
    return _LEFT_OUT if text is None else text


@contextmanager
def _converting(name: str) -> Generator[None]:
    """Raise ``ArgumentError`` if a parameter's value can't become text.

    Such as ``bytes`` that aren't UTF-8, or an object pydantic can't
    serialize, so the error names the parameter, and nothing is sent.
    """
    try:
        yield
    except (UnicodeDecodeError, PydanticSerializationError) as error:
        raise ArgumentError(f"Can't send {name!r}: {error}. No request was sent.", parameter=name) from error


# --- The path -----------------------------------------------------------------
# A "." or ".." segment would move up the path, so it's encoded too.
_DOT_SEGMENTS = {".": "%2E", "..": "%2E%2E"}


def _build_path(path: tuple[str | PathPlaceholder, ...], arguments: Mapping[str, object]) -> str:
    """Return the path with each placeholder filled with its encoded value.

    The planner checked that every placeholder names a parameter, so
    ``arguments`` has a value for each.
    """
    parts: list[str] = []
    for part in path:
        if isinstance(part, str):
            parts.append(part)
            continue
        with _converting(part.name):
            parts.append(_encode_path_value(part, arguments[part.name]))
    return "".join(parts)


def _encode_path_value(placeholder: PathPlaceholder, value: object) -> str:
    """Return ``value`` as percent-encoded text for ``placeholder``.

    Every character that isn't unreserved is encoded, slashes too unless the
    placeholder keeps them, so a value can't add segments, a query string or a
    fragment.

    Raises:
        ArgumentError: If the value is ``None`` or empty, or, for a
            ``{name:path}`` placeholder, has an empty segment. Each would call a
            different path: ``/users/{user_id}`` with ``""`` would call
            ``/users/``.
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


def _path_value_error(placeholder: PathPlaceholder, value: object, problem: str) -> ArgumentError:
    """Return the error for a value that would call a different path."""
    return ArgumentError(
        f"Can't fill {placeholder} with {value!r}: {problem}, so a different path would be called. "
        "No request was sent.",
        parameter=placeholder.name,
    )


# --- Parameters sent under a key ----------------------------------------------
def _text_value(value: object, *, many: bool) -> str | list[str] | None:
    """Return a query, header or form value as text, or ``None`` to omit it.

    ``None`` is left out, and so is an empty collection: "no values" behaves
    like "no value". A ``None`` item in a collection is left out too. Where
    ``many`` allows a collection, the value decides: a ``str`` passed for a
    ``Sequence[str]`` is one value, not one per character.
    """
    if value is None:
        return None
    if not (many and _is_several(value)):
        return _to_text(value)
    texts = [_to_text(item) for item in cast("Iterable[object]", value) if item is not None]
    return texts or None


def _is_several(value: object, *, tuples_too: bool = True) -> bool:
    """Return whether the value is a collection of values, rather than one.

    ``str`` and ``bytes`` are collections, but each is one value. A file's
    tuple is one file, so files pass ``tuples_too=False``.
    """
    if not isinstance(value, Collection) or isinstance(value, str | bytes | bytearray | Mapping):
        return False
    return tuples_too or not isinstance(value, tuple)


def _spread(item: SpreadParameter, value: object) -> dict[str, object]:
    """Return a spread parameter's fields as text, by the key each goes under.

    A model or dataclass is dumped with the plan's ``DumpOptions`` first, so a
    field ``exclude_unset`` leaves out isn't sent; then each field the plan
    lists is sent under its planned key. What a mapping, or a model with its
    own model serializer, dumps is sent under its own keys. A field that's
    ``None`` or an empty collection is left out.

    Raises:
        ArgumentError: If a model's own serializer dumps it to something other
            than a mapping, which can't be spread.
    """
    if item.keys is None:
        source = dict(cast("Mapping[object, object]", value)) if isinstance(value, Mapping) else value
        dumped = _dump(source, item.dump, by_alias=True)
        if not isinstance(dumped, dict):
            raise ArgumentError(
                f"Can't spread {item.name!r}: it dumps to {type(dumped).__name__}, not a mapping of keys to "
                "values. No request was sent.",
                parameter=item.name,
            )
        pairs = [(str(key), field) for key, field in cast("dict[object, object]", dumped).items()]
    else:
        dumped = cast("dict[str, object]", _dump(value, item.dump, by_alias=False))
        pairs = [(key, dumped[attribute]) for attribute, key in item.keys if attribute in dumped]
    fields: dict[str, object] = {}
    for key, field in pairs:
        # Dumped to JSON-ready data, so any collection is a list by now. It
        # repeats the key where the argument takes lists; in a header, it's one
        # value, JSON text.
        text = _text_value(field, many=item.many and isinstance(field, list))
        if text is not None:
            fields[key] = text
    return fields


def _files(item: PlannedParameter, value: object) -> list[object]:
    """Return the files to send under the parameter's key, as they are.

    One file, or each file of a collection, which repeats the field. ``None``,
    an empty collection and a ``None`` in one send none. A tuple is one file,
    ``(filename, content...)``, and ``bytes`` are one file's content.
    """
    if value is None:
        return []
    several = item.many and _is_several(value, tuples_too=False)
    files = list(cast("Iterable[object]", value)) if several else [value]
    return [file for file in files if file is not None]


# --- The body -----------------------------------------------------------------
def _body(body: PlannedParameter, value: object) -> dict[str, object]:
    """Return the ``build_request`` argument for the whole body, if any.

    ``Body()`` is passed as it is, as ``content``; a lone JSON body is dumped as
    ``json``. ``None`` means no body, never ``null``.
    """
    if value is None:
        return {}
    if body.httpx_argument is HttpxArgument.CONTENT:
        return {"content": value}
    return {"json": _dump_json(body, value)}


# --- Text ---------------------------------------------------------------------
def _to_text(value: object) -> str:
    """Return ``value`` as the text that's sent for it.

    It's pydantic's JSON form: an ``Enum`` becomes its value, a ``datetime``
    ISO 8601 text, a ``UUID`` or ``Decimal`` its string, a number or ``bool``
    JSON text (``2``, ``true``), and a list or dict JSON text. Only an object
    pydantic doesn't know uses ``str``: the ``Any`` escape hatch.
    """
    jsonable = to_jsonable_python(value, fallback=str)
    return jsonable if isinstance(jsonable, str) else json.dumps(jsonable)


# --- Dumping values -----------------------------------------------------------
# Dumps a value by its own type, at the call: models nested anywhere in it get
# the dump options too, as in list[User].
_BY_VALUE = TypeAdapter[Any](Any)


def _dump(value: object, dump: DumpOptions, *, by_alias: bool) -> object:
    """Return a spread value's fields as JSON-ready data, with dump options.

    A model is dumped by attribute name, which the plan maps to keys; a
    mapping, or a model with its own model serializer, by alias. A field
    pydantic doesn't know uses ``str``: the ``Any`` escape hatch, as for any
    text value.
    """
    return _BY_VALUE.dump_python(
        value,
        mode="json",
        by_alias=by_alias,
        exclude_unset=dump.exclude_unset,
        exclude_none=dump.exclude_none,
        exclude_defaults=dump.exclude_defaults,
        fallback=str,
    )


def _dump_json(item: PlannedParameter, value: object) -> object:
    """Return a JSON field's or body's value as JSON-ready data, by alias.

    There's no ``str`` fallback here: JSON has no one text form for an object
    pydantic doesn't know.

    Raises:
        ArgumentError: If pydantic can't serialize the value, as for a class it
            doesn't know passed through ``Any``. No request is sent.
    """
    try:
        return _BY_VALUE.dump_python(
            value,
            mode="json",
            by_alias=True,
            exclude_unset=item.dump.exclude_unset,
            exclude_none=item.dump.exclude_none,
            exclude_defaults=item.dump.exclude_defaults,
        )
    except PydanticSerializationError as error:
        raise ArgumentError(
            f"Can't send {item.name!r} as JSON: {error}. Pass a value pydantic can serialize, such as a model, "
            "dataclass, dict or list, or convert it at the call. No request was sent.",
            parameter=item.name,
        ) from error
