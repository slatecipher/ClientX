import inspect
from typing import Annotated

import pytest
from pydantic import BaseModel, Field, computed_field

from clientx._annotation_extractor import AnnotationExtractor, AnnotationInfo, NamedAnnotation, NamedAnnotationExtractor
from clientx._annotations import (
    DumpConfig,
    FieldX,
    RequestPart,
)

type UserIdParam = Annotated[int, FieldX(RequestPart.PARAMS, key="userId")]
type QueryParam[T] = Annotated[T, FieldX(RequestPart.PARAMS)]
type DescribedUserId = Annotated[UserIdParam, "described"]
type IgnoresItsParameter[T] = Annotated[int, FieldX(RequestPart.HEADERS)]
type Cycle = OtherCycle
type OtherCycle = Cycle


def test_request_section_get():
    assert RequestPart.get("json") is RequestPart.JSON
    assert RequestPart.get("params") is RequestPart.PARAMS
    assert RequestPart.get("missing") is None


def test_annotation_info_fieldx_first_match():
    first = FieldX(RequestPart.PARAMS)
    second = FieldX(RequestPart.JSON)
    info = AnnotationInfo(metadata=["meta", first, second])

    assert info.fieldx is first


def test_annotation_info_fieldx_defaults_when_missing():
    info = AnnotationInfo(metadata=["meta"])

    assert info.fieldx.request_part is None
    assert info.fieldx.dump_config == {}


def test_annotation_info_fieldx_dump_config_first_match():
    first = FieldX(RequestPart.DATA, dump_config=DumpConfig(exclude_none=True))
    second = FieldX(RequestPart.JSON, dump_config=DumpConfig(exclude_unset=True))
    info = AnnotationInfo(metadata=["meta", first, second])

    assert info.fieldx.dump_config == {"exclude_none": True}


def test_annotation_extractor_from_field_annotation_with_annotated_metadata():
    info = AnnotationExtractor.from_field_annotation(
        Annotated[int, FieldX(RequestPart.HEADERS, dump_config=DumpConfig(exclude_none=True))]
    )

    assert info.annotation is int
    assert info.metadata == [FieldX(RequestPart.HEADERS, dump_config=DumpConfig(exclude_none=True))]


def test_annotation_extractor_from_signature_maps_annotations():
    def handler(a: int, b: Annotated[str, FieldX(RequestPart.PARAMS)]) -> None: ...

    mapping = AnnotationExtractor.from_signature(inspect.signature(handler))

    assert mapping["a"].annotation is int
    assert mapping["b"].fieldx.request_part is RequestPart.PARAMS


def test_annotation_extractor_from_base_model_includes_aliases_and_computed_fields():
    class Example(BaseModel):
        token: Annotated[str, FieldX(RequestPart.HEADERS)] = Field(alias="auth")

        @computed_field
        @property
        def qs(self) -> Annotated[dict[str, int], FieldX(RequestPart.PARAMS)]:
            return {"q": 1}

    mapping = AnnotationExtractor.from_base_model(Example)

    assert mapping["token"].fieldx.request_part is RequestPart.HEADERS
    assert mapping["auth"].fieldx.request_part is RequestPart.HEADERS
    assert mapping["qs"].fieldx.request_part is RequestPart.PARAMS


def test_annotation_extractor_from_base_model_includes_serialization_aliases():
    class Example(BaseModel):
        token: Annotated[str, FieldX(RequestPart.HEADERS)] = Field(serialization_alias="authToken")

    mapping = AnnotationExtractor.from_base_model(Example)

    assert mapping["authToken"].fieldx.request_part is RequestPart.HEADERS


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


def test_annotation_extractor_reads_metadata_through_a_type_alias():
    info = AnnotationExtractor.from_field_annotation(UserIdParam)

    assert info.annotation is int
    assert info.fieldx.key == "userId"


def test_annotation_extractor_reads_metadata_through_a_generic_type_alias():
    info = AnnotationExtractor.from_field_annotation(QueryParam[list[str]])

    assert info.annotation == list[str]
    assert info.fieldx.request_part is RequestPart.PARAMS


def test_annotation_extractor_puts_inner_alias_metadata_first():
    # Like Python's own flattening of Annotated[Annotated[T, inner], outer].
    nested = AnnotationExtractor.from_field_annotation(Annotated[UserIdParam, "outer"])
    alias_of_alias = AnnotationExtractor.from_field_annotation(DescribedUserId)

    assert nested.annotation is int
    assert nested.metadata == [FieldX(RequestPart.PARAMS, key="userId"), "outer"]
    assert alias_of_alias.metadata == [FieldX(RequestPart.PARAMS, key="userId"), "described"]


def test_annotation_extractor_reads_alias_metadata_on_model_fields():
    class Filters(BaseModel):
        user_id: UserIdParam
        tags: Annotated[QueryParam[list[str]], Field(description="Tags to match")]

    mapping = AnnotationExtractor.from_base_model(Filters)

    assert mapping["user_id"].fieldx.key == "userId"
    assert mapping["tags"].fieldx.request_part is RequestPart.PARAMS
    assert mapping["tags"].annotation == list[str]


def test_annotation_extractor_stops_on_cyclic_type_aliases():
    info = AnnotationExtractor.from_field_annotation(Cycle)

    assert info.metadata == []


def test_annotation_extractor_reads_a_generic_alias_whose_value_takes_no_arguments():
    info = AnnotationExtractor.from_field_annotation(IgnoresItsParameter[str])

    assert info.annotation is int
    assert info.fieldx.request_part is RequestPart.HEADERS
