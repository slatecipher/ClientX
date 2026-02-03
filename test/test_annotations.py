import inspect
from typing import Annotated

import pytest
from pydantic import BaseModel, Field, computed_field

from clientx.annotations import (
    AnnotationExtractor,
    AnnotationInfo,
    NamedAnnotation,
    NamedAnnotationExtractor,
    RequestSection,
)


def test_request_section_get():
    assert RequestSection.get("json") is RequestSection.JSON
    assert RequestSection.get("params") is RequestSection.PARAMS
    assert RequestSection.get("missing") is None


def test_annotation_info_request_section_first_match():
    info = AnnotationInfo(metadata=["meta", RequestSection.PARAMS, RequestSection.JSON])

    assert info.request_section is RequestSection.PARAMS


def test_annotation_extractor_from_field_annotation_with_annotated_metadata():
    info = AnnotationExtractor.from_field_annotation(Annotated[int, RequestSection.HEADERS, "meta"])

    assert info.annotation is int
    assert info.metadata == [RequestSection.HEADERS, "meta"]


def test_annotation_extractor_from_signature_maps_annotations():
    def handler(a: int, b: Annotated[str, RequestSection.PARAMS]) -> None: ...

    mapping = AnnotationExtractor.from_signature(inspect.signature(handler))

    assert mapping["a"].annotation is int
    assert mapping["b"].request_section is RequestSection.PARAMS


def test_annotation_extractor_from_base_model_includes_aliases_and_computed_fields():
    class Example(BaseModel):
        token: Annotated[str, RequestSection.HEADERS] = Field(alias="auth")

        @computed_field
        @property
        def qs(self) -> Annotated[dict[str, int], RequestSection.PARAMS]:
            return {"q": 1}

    mapping = AnnotationExtractor.from_base_model(Example)

    assert mapping["token"].request_section is RequestSection.HEADERS
    assert mapping["auth"].request_section is RequestSection.HEADERS
    assert mapping["qs"].request_section is RequestSection.PARAMS


def test_named_annotation_validation_wraps_errors():
    annotation = NamedAnnotation(name="field", info=AnnotationInfo(annotation=int))

    with pytest.raises(ValueError, match="field"):
        annotation.validate("not-an-int")


def test_named_annotation_extractor_from_signature():
    def handler(a: int) -> None: ...

    mapping = NamedAnnotationExtractor.from_signature(inspect.signature(handler))

    assert mapping["a"].name == "a"
    assert mapping["a"].info.annotation is int
