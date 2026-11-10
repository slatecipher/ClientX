import inspect
from typing import Annotated

import pytest
from pydantic import BaseModel, Field, computed_field

from clientx._annotation_extractor import AnnotationExtractor, AnnotationInfo, NamedAnnotation, NamedAnnotationExtractor
from clientx._annotations import (
    Body,
    DumpConfig,
    File,
    Form,
    Header,
    Part,
    Query,
)

type UserIdParam = Annotated[int, Query("userId")]
type QueryParam[T] = Annotated[T, Query()]
type DescribedUserId = Annotated[UserIdParam, "described"]
type IgnoresItsParameter[T] = Annotated[int, Header()]
type Cycle = OtherCycle  # pyright: ignore[reportGeneralTypeIssues]  # deliberately cyclic
type OtherCycle = Cycle


def test_annotation_info_part_first_match():
    first = Query()
    second = Body()
    info = AnnotationInfo(metadata=["meta", first, second])

    assert info.part is first


def test_annotation_info_part_defaults_when_missing():
    info = AnnotationInfo(metadata=["meta"])

    assert info.part.request_part is None
    assert info.part.dump_config == {}


def test_annotation_info_part_dump_config_first_match():
    first = Form(dump_config=DumpConfig(exclude_none=True))
    second = Body(dump_config=DumpConfig(exclude_unset=True))
    info = AnnotationInfo(metadata=["meta", first, second])

    assert info.part.dump_config == {"exclude_none": True}


def test_annotation_extractor_from_field_annotation_with_annotated_metadata():
    info = AnnotationExtractor.from_field_annotation(Annotated[int, Header(dump_config=DumpConfig(exclude_none=True))])

    assert info.annotation is int
    assert info.metadata == [Header(dump_config=DumpConfig(exclude_none=True))]


def test_annotation_extractor_from_signature_maps_annotations():
    def handler(a: int, b: Annotated[str, Query()]) -> None: ...

    mapping = AnnotationExtractor.from_signature(inspect.signature(handler))

    assert mapping["a"].annotation is int
    assert mapping["b"].part.request_part == "params"


def test_annotation_extractor_from_base_model_includes_aliases_and_computed_fields():
    class Example(BaseModel):
        token: Annotated[str, Header()] = Field(alias="auth")

        @computed_field
        @property
        def qs(self) -> Annotated[dict[str, int], Query()]:
            return {"q": 1}

    mapping = AnnotationExtractor.from_base_model(Example)

    assert mapping["token"].part.request_part == "headers"
    assert mapping["auth"].part.request_part == "headers"
    assert mapping["qs"].part.request_part == "params"


def test_annotation_extractor_from_base_model_includes_serialization_aliases():
    class Example(BaseModel):
        token: Annotated[str, Header()] = Field(serialization_alias="authToken")

    mapping = AnnotationExtractor.from_base_model(Example)

    assert mapping["authToken"].part.request_part == "headers"


def test_named_annotation_validation_wraps_errors():
    annotation = NamedAnnotation(name="field", info=AnnotationInfo(annotation=int))

    with pytest.raises(ValueError, match="field"):
        annotation.validate("not-an-int")


def test_named_annotation_extractor_from_signature():
    def handler(a: int) -> None: ...

    mapping = NamedAnnotationExtractor.from_signature(inspect.signature(handler))

    assert mapping["a"].name == "a"
    assert mapping["a"].info.annotation is int


def test_annotation_extractor_from_field_info_rejects_invalid_type():
    with pytest.raises(TypeError, match="Expected FieldInfo or ComputedFieldInfo, got object"):
        AnnotationExtractor.from_field_info(object())  # type: ignore[arg-type]


def test_dump_config_typed_dict_returns_fields():
    options = DumpConfig(exclude_none=True, exclude_defaults=True)

    assert options == {
        "exclude_none": True,
        "exclude_defaults": True,
    }


def test_dump_config_keys_are_model_dump_options():
    """DumpConfig is a chosen subset of model_dump's options, not a full copy, so it needn't track new ones.

    Every key must still be a model_dump parameter. If this fails under the lowest-versions
    CI job, an option we list is newer than our pydantic lower bound.
    """
    dump_options = set(inspect.signature(BaseModel.model_dump).parameters) - {"self"}

    assert DumpConfig.__required_keys__ == frozenset()
    assert DumpConfig.__optional_keys__ - dump_options == set()


def test_annotation_extractor_reads_metadata_through_a_type_alias():
    info = AnnotationExtractor.from_field_annotation(UserIdParam)

    assert info.annotation is int
    assert info.part.key == "userId"


def test_annotation_extractor_reads_metadata_through_a_generic_type_alias():
    info = AnnotationExtractor.from_field_annotation(QueryParam[list[str]])

    assert info.annotation == list[str]
    assert info.part.request_part == "params"


def test_annotation_extractor_puts_inner_alias_metadata_first():
    # Like Python's own flattening of Annotated[Annotated[T, inner], outer].
    nested = AnnotationExtractor.from_field_annotation(Annotated[UserIdParam, "outer"])
    alias_of_alias = AnnotationExtractor.from_field_annotation(DescribedUserId)

    assert nested.annotation is int
    assert nested.metadata == [Query("userId"), "outer"]
    assert alias_of_alias.metadata == [Query("userId"), "described"]


def test_annotation_extractor_reads_alias_metadata_on_model_fields():
    class Filters(BaseModel):
        user_id: UserIdParam
        tags: Annotated[QueryParam[list[str]], Field(description="Tags to match")]

    mapping = AnnotationExtractor.from_base_model(Filters)

    assert mapping["user_id"].part.key == "userId"
    assert mapping["tags"].part.request_part == "params"
    assert mapping["tags"].annotation == list[str]


def test_annotation_extractor_stops_on_cyclic_type_aliases():
    info = AnnotationExtractor.from_field_annotation(Cycle)

    assert info.metadata == []


def test_annotation_extractor_reads_a_generic_alias_whose_value_takes_no_arguments():
    info = AnnotationExtractor.from_field_annotation(IgnoresItsParameter[str])

    assert info.annotation is int
    assert info.part.request_part == "headers"


@pytest.mark.parametrize(
    ("helper", "request_part"),
    [
        (Query, "params"),
        (Header, "headers"),
        (Form, "data"),
        (Body, "json"),
        (File, "files"),
    ],
)
def test_each_helper_is_a_part_with_a_fixed_request_part(helper: type[Part], request_part: str):
    marker = helper()

    assert isinstance(marker, Part)
    assert marker.request_part == request_part
    assert marker.key is None
    assert marker.dump_config == {}


@pytest.mark.parametrize("helper", [Query, Header, Form])
def test_keyed_helpers_take_the_key_first(helper: type[Query]):
    marker = helper("userId", dump_config=DumpConfig(exclude_none=True))

    assert list(inspect.signature(helper).parameters) == ["key", "dump_config"]
    assert marker.key == "userId"
    assert marker.dump_config == {"exclude_none": True}


@pytest.mark.parametrize("helper", [Body, File])
def test_body_and_file_take_no_key(helper: type[Body]):
    assert list(inspect.signature(helper).parameters) == ["dump_config"]
    with pytest.raises(TypeError):
        helper("key")  # pyright: ignore[reportCallIssue]
