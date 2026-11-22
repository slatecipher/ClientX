"""Validate an endpoint's arguments against its parameters' annotations.

One validator covers all of an endpoint's parameters: Pydantic validates a call
to a stand-in function with the same parameters, so each annotation applies in
full, a helper's constraints (``Query(ge=1)``) included. Arguments are matched
by parameter name, never by a helper's alias, which is the name sent to the
API. ``clientx.tools`` validates a model's arguments with it.

A client created with ``validate_arguments=True`` checks each call's arguments
before anything is sent:

- Only the arguments the caller passed, not the defaults filled in, so
  ``page: int = None`` doesn't fail when ``page`` is left out.
- Strictly, as a type checker would: ``"7"`` doesn't fit an ``int``. A model
  instance isn't validated again, as is Pydantic's default.
- The request is built from the caller's values, not from what Pydantic
  returns, so validation never changes what's sent.
- A parameter whose annotation Pydantic can't validate isn't checked: a
  binary file (``IO[bytes]``, ``BinaryIO``, or a file tuple holding one),
  ``Iterator[bytes]`` or an async stream, or a class Pydantic doesn't know.
  A stream's items are never checked: Pydantic validates an ``Iterable``
  lazily, and what it returns is thrown away.
- An endpoint's validator is built on its first checked call, so a client that
  doesn't check doesn't pay for it.
- A failure raises ``ArgumentError`` for the first parameter that doesn't fit,
  with every problem in its message and Pydantic's ``ValidationError`` as its
  cause.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from pydantic import ConfigDict, PydanticSchemaGenerationError, TypeAdapter, ValidationError

from clientx.exceptions import ArgumentError

if TYPE_CHECKING:
    from clientx._signature import ParameterInfo


# --- Validators ---------------------------------------------------------------
_BY_NAME = ConfigDict(validate_by_name=True, validate_by_alias=False)


def arguments_adapter(parameters: Sequence[ParameterInfo]) -> TypeAdapter[dict[str, Any]]:
    """Return a validator of arguments, by name, for these parameters.

    It validates a call to a stand-in with these parameters, all keyword-only
    so a mapping fills them, and returns the arguments, defaults included: the
    endpoint itself isn't called, so validating its arguments can't send a
    request.

    Raises:
        PydanticSchemaGenerationError: If Pydantic can't build a schema for a
            parameter's annotation.
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


def build_arguments_validator(parameters: Sequence[ParameterInfo]) -> TypeAdapter[dict[str, Any]]:
    """Return the validator ``check_arguments`` takes, for these parameters.

    A parameter whose annotation Pydantic can't validate, such as ``BinaryIO``,
    is validated as ``Any``, so the others are still checked.
    """
    try:
        return arguments_adapter(parameters)
    except PydanticSchemaGenerationError:
        return arguments_adapter([p if _can_validate(p.annotation) else replace(p, annotation=Any) for p in parameters])


def _can_validate(annotation: Any) -> bool:
    try:
        TypeAdapter[Any](annotation)
    except PydanticSchemaGenerationError:
        return False
    return True


# --- Checking a call ----------------------------------------------------------
def check_arguments(validator: TypeAdapter[dict[str, Any]], arguments: Mapping[str, Any], endpoint: str) -> None:
    """Raise ``ArgumentError`` unless ``arguments`` fit, strictly.

    ``endpoint`` is the endpoint's qualified name, for the message.
    """
    try:
        validator.validate_python(dict(arguments), strict=True)
    except ValidationError as error:
        parameter = str(error.errors()[0]["loc"][0])
        raise ArgumentError(
            f"The arguments to '{endpoint}' don't fit their annotations: {describe_errors(error, values=True)}. "
            "No request was sent.",
            parameter=parameter,
        ) from error


# --- Error messages -----------------------------------------------------------
def describe_errors(error: ValidationError, *, values: bool) -> str:
    """Return each of Pydantic's errors as ``where: what``, without its URL.

    With ``values``, a value that's there but doesn't fit is shown too, short:
    it's the caller's own argument. A response's values aren't.
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
