import inspect
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from datetime import datetime
from typing import Annotated, Any

import httpx2
import pytest
from pydantic import BaseModel, Field, ValidationError
from pydantic.fields import FieldInfo

import clientx.arguments
from clientx._arguments import HttpxArgumentSpec, bind_argument
from clientx.arguments import (
    Body,
    Cookie,
    File,
    Form,
    Header,
    HttpxArgument,
    Json,
    Query,
    Url,
    get_argument_location,
)

HELPERS = [
    pytest.param(Url, HttpxArgument.URL, id="Url"),
    pytest.param(Query, HttpxArgument.PARAMS, id="Query"),
    pytest.param(Header, HttpxArgument.HEADERS, id="Header"),
    pytest.param(Cookie, HttpxArgument.COOKIES, id="Cookie"),
    pytest.param(Body, HttpxArgument.CONTENT, id="Body"),
    pytest.param(Form, HttpxArgument.DATA, id="Form"),
    pytest.param(File, HttpxArgument.FILES, id="File"),
    pytest.param(Json, HttpxArgument.JSON, id="Json"),
]


def locations(model: type[BaseModel], field_name: str) -> list[HttpxArgument]:
    """The request parts a model field is marked for, in metadata order."""
    return [item.in_ for item in model.model_fields[field_name].metadata if isinstance(item, HttpxArgumentSpec)]


# --------------------------------------------------------------------------- #
# HttpxArgument, HttpxArgumentLocation and get_argument_location
# --------------------------------------------------------------------------- #


def test_parts_match_httpx_build_request_one_to_one():
    """The design rule: one part per build_request argument that carries request data."""
    arguments = set(inspect.signature(httpx2.Client.build_request).parameters)

    assert {part.value for part in HttpxArgument} == arguments - {"self", "method", "timeout", "extensions"}


def test_parts_are_strings():
    assert HttpxArgument.JSON == "json"
    assert str(HttpxArgument.PARAMS) == "params"
    assert HttpxArgument("headers") is HttpxArgument.HEADERS


def test_location_is_a_frozen_value():
    location = HttpxArgumentSpec(in_=HttpxArgument.JSON)

    assert location == HttpxArgumentSpec(in_=HttpxArgument.JSON)
    assert location != HttpxArgumentSpec(in_=HttpxArgument.DATA)
    assert hash(location) == hash(HttpxArgumentSpec(in_=HttpxArgument.JSON))
    with pytest.raises(FrozenInstanceError):
        location.in_ = HttpxArgument.DATA  # pyright: ignore[reportAttributeAccessIssue]


def test_get_argument_location_reads_the_mark():
    class Model(BaseModel):
        dry_run: bool = Query(default=False)
        username: Annotated[str, Json(min_length=3)]
        email: str = Field()

    assert get_argument_location(Query()) == HttpxArgument.PARAMS
    assert {name: get_argument_location(field) for name, field in Model.model_fields.items()} == {
        "dry_run": HttpxArgument.PARAMS,
        "username": HttpxArgument.JSON,
        "email": None,
    }
    assert get_argument_location("not a field") is None


# --------------------------------------------------------------------------- #
# The helpers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("helper", "part"), HELPERS)
def test_helper_returns_a_field_marked_for_its_part(helper: Callable[..., Any], part: HttpxArgument):
    field_info = helper()

    assert isinstance(field_info, FieldInfo)
    assert field_info.metadata == [HttpxArgumentSpec(in_=part)]


@pytest.mark.parametrize(("helper", "part"), HELPERS)
def test_helper_has_its_own_name_docstring_and_fields_signature(helper: Callable[..., Any], part: HttpxArgument):
    assert getattr(clientx.arguments, helper.__name__) is helper  # Named as it's exported.
    assert helper.__qualname__ == helper.__name__
    assert helper.__module__ == "clientx.arguments"
    assert helper.__doc__ is not None
    assert f"request's ``{part}``" in helper.__doc__
    assert inspect.signature(helper) == inspect.signature(Field)  # help() shows Field's arguments.


@pytest.mark.parametrize(("helper", "part"), HELPERS)
def test_model_field_keeps_its_part(helper: Callable[..., Any], part: HttpxArgument):
    class Model(BaseModel):
        value: str = helper(default="x")

    assert locations(Model, "value") == [part]


def test_each_call_creates_a_new_field():
    first, second = Query(), Query()

    assert first is not second
    assert second.metadata == [HttpxArgumentSpec(in_=HttpxArgument.PARAMS)]  # Not marked twice.


def test_fields_in_one_model_are_marked_independently():
    class CreateUserRequest(BaseModel):
        org_id: int = Url(gt=0)
        dry_run: bool = Query(default=False)
        authorization: str = Header(alias="Authorization")
        session: str = Cookie(default="")
        username: str = Json(min_length=3)
        email: str = Field()

    assert {name: locations(CreateUserRequest, name) for name in CreateUserRequest.model_fields} == {
        "org_id": [HttpxArgument.URL],
        "dry_run": [HttpxArgument.PARAMS],
        "authorization": [HttpxArgument.HEADERS],
        "session": [HttpxArgument.COOKIES],
        "username": [HttpxArgument.JSON],
        "email": [],
    }


def test_location_comes_after_fields_own_metadata():
    field_info = Url(gt=0)

    assert len(field_info.metadata) == 2
    assert field_info.metadata[-1] == HttpxArgumentSpec(in_=HttpxArgument.URL)


def test_helper_inside_annotated():
    class Model(BaseModel):
        org_id: Annotated[int, Url(gt=0)]

    assert locations(Model, "org_id") == [HttpxArgument.URL]
    assert Model(org_id=1).org_id == 1
    with pytest.raises(ValidationError):
        Model(org_id=0)


def test_subclass_inherits_marked_fields():
    class Base(BaseModel):
        username: str = Json()

    class Child(Base):
        pass

    assert locations(Child, "username") == [HttpxArgument.JSON]


# --------------------------------------------------------------------------- #
# Everything else is pydantic.Field's
# --------------------------------------------------------------------------- #


def test_field_arguments_pass_through():
    field_info = Query(default=5, description="Page size", title="Limit", examples=[10], le=100)

    assert field_info.default == 5
    assert field_info.description == "Page size"
    assert field_info.title == "Limit"
    assert field_info.examples == [10]


def test_positional_default_passes_through():
    assert Query(7).default == 7


def test_required_and_default_factory():
    class Model(BaseModel):
        username: str = Json()
        explicit: str = Json(...)
        tags: list[str] = Query(default_factory=list[str])

    with pytest.raises(ValidationError) as error:
        Model()
    assert {item["loc"][0] for item in error.value.errors()} == {"username", "explicit"}
    assert Model(username="ada", explicit="x").tags == []


def test_constraints_are_validated():
    class Model(BaseModel):
        org_id: int = Url(gt=0)
        username: str = Json(min_length=3)

    assert Model(org_id=1, username="ada").model_dump() == {"org_id": 1, "username": "ada"}
    with pytest.raises(ValidationError) as error:
        Model(org_id=0, username="ab")
    assert {item["type"] for item in error.value.errors()} == {"greater_than", "string_too_short"}


def test_alias_is_used_to_create_and_to_dump():
    class Model(BaseModel):
        timestamp: datetime = Query(alias="timeStamp")

    moment = datetime(2026, 11, 15, 9, 30)

    assert Model(timeStamp=moment).model_dump(by_alias=True) == {"timeStamp": moment}  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValidationError):
        Model(timestamp=moment)


def test_serialization_alias_is_used_only_to_dump():
    class Model(BaseModel):
        timestamp: datetime = Query(serialization_alias="timeStamp")

    moment = datetime(2026, 11, 15, 9, 30)
    model = Model(timestamp=moment)

    assert model.model_dump(by_alias=True) == {"timeStamp": moment}
    assert model.model_dump() == {"timestamp": moment}


def test_location_doesnt_change_the_json_schema():
    class Marked(BaseModel):
        username: str = Json(min_length=3, description="Login name")

    class Plain(BaseModel):
        username: str = Field(min_length=3, description="Login name")

    assert Marked.model_json_schema()["properties"] == Plain.model_json_schema()["properties"]


# --------------------------------------------------------------------------- #
# bind_argument with another Field-like function
# --------------------------------------------------------------------------- #


def test_bind_argument_passes_arguments_through_and_marks_the_result():
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def make_field(*args: Any, **kwargs: Any) -> FieldInfo:
        calls.append((args, kwargs))
        return Field(*args, **kwargs)

    helper = bind_argument("Custom", HttpxArgument.HEADERS, make_field)
    field_info = helper(1, description="d")

    assert calls == [((1,), {"description": "d"})]
    assert helper.__name__ == "Custom"
    assert inspect.signature(helper) == inspect.signature(make_field)
    assert field_info.default == 1
    assert field_info.metadata == [HttpxArgumentSpec(in_=HttpxArgument.HEADERS)]


# --------------------------------------------------------------------------- #
# Known problems, found while writing these tests (2026-11-15). Not tested yet, because the right
# behavior is still to decide. File them as one GitHub issue when this experiment heads for a pull request.
#
#   1. Type checkers don't treat the helpers as field specifiers (the module docstring's known limitation):
#      every marked field looks optional to them, and they don't see `alias`. test_alias_is_used_to_create_and_to_dump
#      needs a pyright ignore for the call that works at runtime.
# --------------------------------------------------------------------------- #
