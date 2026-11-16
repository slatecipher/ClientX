import functools
import inspect
import json
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

import pytest

from clientx._compiler import SignatureInfo, describe_signature
from clientx._compiler.models import MethodKind, ParameterInfo
from clientx._compiler.type_hints import NO_VALUE

# --------------------------------------------------------------------------- #
# Callables to describe. Classes are at module level so their methods can be
# found from __qualname__; ones defined inside a test are deliberately out of reach.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Range:
    low: int
    high: int


@dataclass(frozen=True)
class Sensitive:
    pass


def create_user(
    user_id: Annotated[int, Range(1, 10)],
    /,
    email: Annotated[str, Sensitive(), "contact"],
    name: str | None = None,
    *tags: str,
    notify: bool = False,
    **extra: object,
) -> Annotated[dict[str, object], "user"]:
    """Create a user.

    Indented details.
    """
    return {}


def untyped(value, flag=True):
    return value


def string_hints(count: "int", label: "Annotated[str, Sensitive()]") -> "list[Range]":
    return []


def unresolvable(missing: "Missing", count: int) -> None:  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
    pass


async def fetch(url: str) -> bytes:
    return b""


def logged[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return function(*args, **kwargs)

    return wrapper


def not_wrapped[**P, R](function: Callable[P, R]) -> Callable[..., R]:
    def wrapper(*args: Any, **kwargs: Any) -> R:
        return function(*args, **kwargs)

    return wrapper


@logged
def decorated(item_id: int, *, verbose: bool = False) -> str:
    """Decorated docstring."""
    return ""


@logged
async def decorated_async(item_id: int) -> str:
    return ""


@not_wrapped
def decorated_without_wraps(item_id: int) -> str:
    return ""


class UserService:
    def create(self, name: str) -> str:
        return name

    add = create  # An alias: the same function under a second name.

    @classmethod
    def build(cls, size: int = 1) -> "UserService":
        return cls()

    @staticmethod
    def normalize(name: str) -> str:
        return name

    class Inner:
        def method(self) -> None:
            pass


class AdminService(UserService):
    pass


def shout(self: object, text: str) -> str:
    return text.upper()


class Speaker:
    yell = shout  # Defined outside the class, so it's only found under another name.


class Point:  # noqa: B903 (a hand-written __init__ is what the constructor tests describe)
    def __init__(self, x: int, y: Annotated[int, Range(0, 9)] = 0) -> None:
        self.x = x
        self.y = y


class Empty:
    pass


def plain_function() -> None:
    pass


@pytest.fixture
def info() -> SignatureInfo:
    return describe_signature(create_user)


# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #


def test_parameters_are_described_in_order_with_their_kind(info: SignatureInfo):
    assert [(p.name, p.position, p.kind) for p in info] == [
        ("user_id", 0, inspect.Parameter.POSITIONAL_ONLY),
        ("email", 1, inspect.Parameter.POSITIONAL_OR_KEYWORD),
        ("name", 2, inspect.Parameter.POSITIONAL_OR_KEYWORD),
        ("tags", 3, inspect.Parameter.VAR_POSITIONAL),
        ("notify", 4, inspect.Parameter.KEYWORD_ONLY),
        ("extra", 5, inspect.Parameter.VAR_KEYWORD),
    ]


def test_annotated_parameters_split_into_base_type_and_metadata(info: SignatureInfo):
    email = info["email"]

    assert email.annotation == Annotated[str, Sensitive(), "contact"]
    assert email.base_type is str
    assert email.metadata == (Sensitive(), "contact")


def test_plain_parameters_have_no_metadata(info: SignatureInfo):
    name = info["name"]

    assert name.annotation == str | None
    assert name.base_type == str | None
    assert name.metadata == ()


def test_defaults(info: SignatureInfo):
    assert info["name"].default is None
    assert info["name"].has_default
    assert info["notify"].default is False
    assert info["email"].default is NO_VALUE
    assert not info["email"].has_default


@pytest.mark.parametrize(
    ("name", "required"),
    [
        pytest.param("user_id", True, id="positional-only"),
        pytest.param("email", True, id="no-default"),
        pytest.param("name", False, id="default"),
        pytest.param("tags", False, id="var-positional"),
        pytest.param("notify", False, id="keyword-only-default"),
        pytest.param("extra", False, id="var-keyword"),
    ],
)
def test_is_required(info: SignatureInfo, name: str, required: bool):
    assert info[name].is_required is required


def test_is_optional_reads_the_type_not_the_default():
    def search(term: str | None, limit: int = 10) -> None:
        pass

    search_info = describe_signature(search)

    assert search_info["term"].is_optional
    assert search_info["term"].is_required
    assert not search_info["limit"].is_optional
    assert not search_info["limit"].is_required


def test_is_optional_looks_through_annotated():
    def search(term: Annotated[str | None, "q"] = None) -> None:
        pass

    assert describe_signature(search)["term"].is_optional


@pytest.mark.parametrize(
    ("name", "positional", "keyword", "variadic"),
    [
        pytest.param("user_id", True, False, False, id="positional-only"),
        pytest.param("email", True, True, False, id="positional-or-keyword"),
        pytest.param("tags", False, False, True, id="var-positional"),
        pytest.param("notify", False, True, False, id="keyword-only"),
        pytest.param("extra", False, False, True, id="var-keyword"),
    ],
)
def test_how_each_kind_can_be_passed(info: SignatureInfo, name: str, positional: bool, keyword: bool, variadic: bool):
    parameter = info[name]

    assert parameter.can_pass_positionally is positional
    assert parameter.can_pass_by_keyword is keyword
    assert parameter.is_variadic is variadic


def test_unannotated_parameters():
    untyped_info = describe_signature(untyped)

    assert not untyped_info["value"].has_annotation
    assert untyped_info["value"].annotation is NO_VALUE
    assert untyped_info["value"].base_type is NO_VALUE
    assert untyped_info["flag"].default is True
    assert untyped_info.returns.annotation is NO_VALUE
    assert info_types(untyped_info) == {"value": "Any", "flag": "Any"}


def info_types(signature_info: SignatureInfo) -> dict[str, str]:
    return {parameter["name"]: parameter["type"] for parameter in signature_info.to_dict()["parameters"]}


def test_metadata_helpers(info: SignatureInfo):
    user_id, email = info["user_id"], info["email"]

    assert user_id.get_metadata(Range) == [Range(1, 10)]
    assert email.get_metadata(str) == ["contact"]
    assert email.get_metadata(Range) == []
    assert user_id.first_metadata(Range) == Range(1, 10)
    assert email.first_metadata(Range) is None
    assert email.first_metadata(Range, Range(0, 0)) == Range(0, 0)
    assert email.has_metadata(Sensitive)
    assert not user_id.has_metadata(Sensitive)


def test_parameter_to_dict_is_json_friendly(info: SignatureInfo):
    assert info["user_id"].to_dict() == {
        "name": "user_id",
        "position": 0,
        "kind": "POSITIONAL_ONLY",
        "type": "int",
        "required": True,
        "default": None,
        "metadata": ["Range(low=1, high=10)"],
    }
    assert info["name"].to_dict()["default"] == "None"  # repr() of the default, so None is "None", not null
    assert info["notify"].to_dict()["default"] == "False"
    json.dumps([parameter.to_dict() for parameter in info])


def test_parameter_info_is_frozen(info: SignatureInfo):
    with pytest.raises(AttributeError):
        info["email"].name = "changed"  # pyright: ignore[reportAttributeAccessIssue]


# --------------------------------------------------------------------------- #
# SignatureInfo as a container and its filtered views
# --------------------------------------------------------------------------- #


def test_lookup_by_name_or_position(info: SignatureInfo):
    assert info["email"] is info[1]
    assert info[-1].name == "extra"
    assert len(info) == 6
    assert "email" in info
    assert "missing" not in info


def test_lookup_of_a_missing_parameter_raises(info: SignatureInfo):
    with pytest.raises(KeyError, match="missing"):
        info["missing"]
    with pytest.raises(IndexError):
        info[6]


def test_filtered_views(info: SignatureInfo):
    def names(parameters: list[ParameterInfo]) -> list[str]:
        return [parameter.name for parameter in parameters]

    assert names(info.required_parameters) == ["user_id", "email"]
    assert names(info.parameters_with_defaults) == ["name", "notify"]
    assert names(info.positional_parameters) == ["user_id", "email", "name"]
    assert names(info.keyword_only_parameters) == ["notify"]
    assert names(info.params_with(Sensitive)) == ["email"]
    assert names(info.params_with(Range)) == ["user_id"]
    assert info.accepts_extra_positional
    assert info.accepts_extra_keywords


def test_no_variadic_parameters():
    simple = describe_signature(plain_function)

    assert len(simple) == 0
    assert not simple.accepts_extra_positional
    assert not simple.accepts_extra_keywords
    assert simple.required_parameters == []


def test_bind_fills_in_defaults_and_collects_variadics(info: SignatureInfo):
    assert info.bind(1, "a@example.com") == {
        "user_id": 1,
        "email": "a@example.com",
        "name": None,
        "tags": (),
        "notify": False,
        "extra": {},
    }
    assert info.bind(1, "a@example.com", "Ada", "x", "y", notify=True, source="web") == {
        "user_id": 1,
        "email": "a@example.com",
        "name": "Ada",
        "tags": ("x", "y"),
        "notify": True,
        "extra": {"source": "web"},
    }


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [
        pytest.param((1,), {}, id="missing"),
        pytest.param((), {"user_id": 1, "email": "a@example.com"}, id="positional-only-by-keyword"),
        pytest.param((1, "a@example.com"), {"email": "b@example.com"}, id="duplicate"),
    ],
)
def test_bind_rejects_arguments_that_dont_fit(info: SignatureInfo, args: tuple[Any, ...], kwargs: dict[str, Any]):
    with pytest.raises(TypeError):
        info.bind(*args, **kwargs)


# --------------------------------------------------------------------------- #
# Return type, names, docs, async
# --------------------------------------------------------------------------- #


def test_return_type(info: SignatureInfo):
    assert info.returns.annotation == Annotated[dict[str, object], "user"]
    assert info.returns.base_type == dict[str, object]
    assert info.returns.metadata == ("user",)
    assert info.returns.get_metadata(str) == ["user"]
    assert info.returns.get_metadata(Range) == []


def test_names_module_and_doc(info: SignatureInfo):
    assert info.func is create_user
    assert info.name == "create_user"
    assert info.qualname == "create_user"
    assert info.module == __name__
    assert info.doc == "Create a user.\n\nIndented details."
    assert describe_signature(plain_function).doc is None


def test_signature_is_the_inspect_signature(info: SignatureInfo):
    assert info.signature == inspect.signature(create_user)


def test_is_async():
    assert describe_signature(fetch).is_async
    assert describe_signature(decorated_async).is_async
    assert not describe_signature(create_user).is_async
    assert describe_signature(UserService.create).is_async is False


def test_signature_to_dict_is_json_friendly(info: SignatureInfo):
    described = info.to_dict()

    assert {key: value for key, value in described.items() if key != "parameters"} == {
        "name": "create_user",
        "module": __name__,
        "async": False,
        "method_kind": "function",
        "owner": None,
        "bound": False,
        "returns": "dict[str, object]",
    }
    assert described["parameters"] == [parameter.to_dict() for parameter in info]
    json.dumps(described)


def test_each_call_returns_an_equal_but_new_object(info: SignatureInfo):
    again = describe_signature(create_user)

    assert again == info
    assert again is not info


# --------------------------------------------------------------------------- #
# Type hints written as strings, and decorators
# --------------------------------------------------------------------------- #


def test_string_hints_are_resolved_with_their_metadata():
    hinted = describe_signature(string_hints)

    assert hinted["count"].base_type is int
    assert hinted["label"].base_type is str
    assert hinted["label"].metadata == (Sensitive(),)
    assert hinted.returns.base_type == list[Range]


def test_unresolvable_hints_fall_back_to_the_raw_annotations():
    hinted = describe_signature(unresolvable)

    assert hinted["missing"].annotation == "Missing"
    assert hinted["missing"].base_type == "Missing"
    assert hinted["count"].base_type is int


def test_functools_wraps_decorators_are_looked_through():
    wrapped = describe_signature(decorated)

    assert wrapped.name == "decorated"
    assert wrapped.doc == "Decorated docstring."
    assert [parameter.name for parameter in wrapped] == ["item_id", "verbose"]
    assert wrapped["item_id"].base_type is int
    assert wrapped["verbose"].kind is inspect.Parameter.KEYWORD_ONLY
    assert wrapped.returns.base_type is str
    assert wrapped.bind(5) == {"item_id": 5, "verbose": False}


def test_decorators_without_wraps_show_the_wrapper():
    wrapped = describe_signature(decorated_without_wraps)

    assert [(p.name, p.kind) for p in wrapped] == [
        ("args", inspect.Parameter.VAR_POSITIONAL),
        ("kwargs", inspect.Parameter.VAR_KEYWORD),
    ]
    assert wrapped.name == "wrapper"
    assert wrapped.method_kind is MethodKind.FUNCTION  # "not_wrapped.<locals>.wrapper": a nested function


# --------------------------------------------------------------------------- #
# Ownership: which class a callable belongs to, and how
# --------------------------------------------------------------------------- #


def test_plain_function():
    described = describe_signature(plain_function)

    assert described.method_kind is MethodKind.FUNCTION
    assert described.owner is None
    assert described.owner_name is None
    assert described.bound_to is None
    assert not described.is_method
    assert not described.is_bound


def test_nested_function():
    def inner() -> None:
        pass

    assert describe_signature(inner).method_kind is MethodKind.FUNCTION


def test_unbound_instance_method_keeps_self():
    described = describe_signature(UserService.create)

    assert described.method_kind is MethodKind.INSTANCE
    assert described.owner is UserService
    assert described.owner_name == "UserService"
    assert described.bound_to is None
    assert described.is_method
    assert not described.is_bound
    assert [parameter.name for parameter in described] == ["self", "name"]


def test_bound_instance_method_drops_self():
    service = UserService()

    described = describe_signature(service.create)

    assert described.method_kind is MethodKind.INSTANCE
    assert described.owner is UserService
    assert described.bound_to is service
    assert described.is_bound
    assert [parameter.name for parameter in described] == ["name"]
    assert described.to_dict()["bound"] is True


@pytest.mark.parametrize(
    "build",
    [pytest.param(UserService.build, id="through-class"), pytest.param(UserService().build, id="through-instance")],
)
def test_class_method_is_bound_to_the_class(build: Callable[..., Any]):
    described = describe_signature(build)

    assert described.method_kind is MethodKind.CLASS
    assert described.owner is UserService
    assert described.bound_to is UserService
    assert described.is_method
    assert [parameter.name for parameter in described] == ["size"]


@pytest.mark.parametrize(
    "normalize",
    [
        pytest.param(UserService.normalize, id="through-class"),
        pytest.param(UserService().normalize, id="through-instance"),
    ],
)
def test_static_method(normalize: Callable[..., Any]):
    described = describe_signature(normalize)

    assert described.method_kind is MethodKind.STATIC
    assert described.owner is UserService
    assert described.bound_to is None
    assert described.is_method
    assert not described.is_bound


def test_unbound_class_method_read_off_the_class_dict():
    raw = inspect.getattr_static(UserService, "build").__func__

    described = describe_signature(raw)

    assert described.method_kind is MethodKind.CLASS
    assert described.owner is UserService
    assert described.bound_to is None
    assert [parameter.name for parameter in described] == ["cls", "size"]


def test_inherited_methods_are_owned_by_the_defining_class():
    admin = AdminService()

    bound = describe_signature(admin.create)
    unbound = describe_signature(AdminService.create)
    class_method = describe_signature(AdminService.build)

    assert bound.owner is UserService
    assert bound.bound_to is admin
    assert unbound.owner is UserService
    assert class_method.owner is UserService
    assert class_method.bound_to is AdminService


def test_alias_is_owned_by_the_defining_class():
    service = UserService()

    described = describe_signature(service.add)

    assert described.method_kind is MethodKind.INSTANCE
    assert described.owner is UserService
    assert described.name == "create"


def test_function_attached_under_another_name_is_owned_by_that_class():
    described = describe_signature(Speaker().yell)

    assert described.owner is Speaker
    assert described.name == "shout"


def test_bound_method_no_class_defines_has_no_owner():
    service = UserService()

    described = describe_signature(types.MethodType(shout, service))

    assert described.method_kind is MethodKind.INSTANCE
    assert described.owner is None
    assert described.owner_name is None
    assert described.bound_to is service
    assert [parameter.name for parameter in described] == ["text"]


def test_method_of_a_nested_class():
    described = describe_signature(UserService.Inner.method)

    assert described.method_kind is MethodKind.INSTANCE
    assert described.owner is UserService.Inner
    assert described.owner_name == "UserService.Inner"


def test_method_of_a_class_defined_in_a_function_is_unknown():
    class Local:
        def method(self) -> None:
            pass

    described = describe_signature(Local.method)

    assert described.method_kind is MethodKind.UNKNOWN
    assert described.owner is None
    assert described.is_method


def test_bound_method_of_a_class_defined_in_a_function_is_found():
    class Local:
        def method(self) -> None:
            pass

    local = Local()

    described = describe_signature(local.method)

    assert described.method_kind is MethodKind.INSTANCE
    assert described.owner is Local
    assert described.bound_to is local


@pytest.mark.parametrize(
    ("module", "qualname"),
    [
        pytest.param("module.that.is.not.loaded", "Ghost.method", id="module-not-loaded"),
        pytest.param(__name__, "Ghost.method", id="class-missing"),
        pytest.param(__name__, "plain_function.method", id="path-ends-at-a-function"),
    ],
)
def test_owner_that_cant_be_found_is_unknown(module: str, qualname: str):
    def method(self: object) -> None:
        pass

    method.__module__ = module
    method.__qualname__ = qualname

    described = describe_signature(method)

    assert described.method_kind is MethodKind.UNKNOWN
    assert described.owner is None


def test_class_is_described_through_its_init():
    described = describe_signature(Point)

    assert described.method_kind is MethodKind.CONSTRUCTOR
    assert described.owner is Point
    assert described.bound_to is None
    assert not described.is_method
    assert [parameter.name for parameter in described] == ["x", "y"]
    assert described["y"].metadata == (Range(0, 9),)
    assert described.bind(1) == {"x": 1, "y": 0}
    assert described.to_dict()["owner"] == "Point"


def test_class_without_init():
    described = describe_signature(Empty)

    assert described.method_kind is MethodKind.CONSTRUCTOR
    assert len(described) == 0


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


def test_not_callable_raises_type_error():
    with pytest.raises(TypeError):
        describe_signature(42)  # pyright: ignore[reportArgumentType]


def test_builtin_without_a_signature_raises_value_error():
    with pytest.raises(ValueError):
        describe_signature(vars)


# --------------------------------------------------------------------------- #
# Known problems, found while writing these tests (2026-11-15). Not fixed yet; file them as one GitHub
# issue when this experiment heads for a pull request.
#
# Tested below, as strict xfail: once fixed, a test passes, which fails the run until its marker is removed.
#   1. describe_signature(SomeClass).returns is NoneType: _resolve_type_hints reads __init__'s hints,
#      including its `-> None`, so a constructor seems to return None instead of an instance of the class.
#   2. A callable instance (an object with __call__), before Python 3.14: typing.get_type_hints raises for
#      an instance, and the fallback reads the class's own __annotations__, not __call__'s. A class attribute
#      with a parameter's name gives that parameter the wrong type. Callable instances aren't in
#      describe_signature's list of supported callables.
#
# Not tested, to decide first:
#   3. `-> None` shows as "NoneType" in SignatureInfo.to_dict()["returns"], because get_type_hints turns None
#      into type(None). describe_type's docstring writes None as "None" ('int | None').
#   4. describe_type(Optional[int]) is "Optional[int]" on 3.12 and 3.13 but "int | None" on 3.14 (str() of a
#      typing.Union changed), so to_dict() output depends on the Python version. The tests use `int | None`.
#   5. type_hints.py's module docstring says it's shared with "inspector.py"; that module is now
#      signature_info.py.
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(reason="A class's return type comes from __init__'s `-> None`, so it's NoneType", strict=True)
def test_class_returns_an_instance_of_itself():
    assert describe_signature(Point).returns.base_type is Point


class Greeter:
    label: str

    def __call__(self, label: int) -> int:
        return label


@pytest.mark.xfail(
    sys.version_info < (3, 14),
    reason="Before 3.14, a callable instance's hints fall back to its class's __annotations__",
    strict=True,
)
def test_callable_instance_uses_its_call_annotations():
    assert describe_signature(Greeter())["label"].base_type is int
