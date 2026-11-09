import pytest

from clientx import ClientX
from clientx.exceptions import (
    ClientXError,
    EndpointNameConflictError,
    MissingDecoderError,
    MissingPathArgumentsError,
    MissingReturnTypeError,
    UnboundResourceError,
    UnconsumableArgumentError,
)
from clientx.methods import get


@pytest.mark.parametrize(
    ("error", "builtin_base"),
    [
        (UnconsumableArgumentError, TypeError),
        (MissingPathArgumentsError, ValueError),
        (MissingReturnTypeError, TypeError),
        (MissingDecoderError, TypeError),
        (EndpointNameConflictError, TypeError),
        (UnboundResourceError, TypeError),
    ],
)
def test_errors_share_clientx_base_and_keep_builtin_base(error: type[Exception], builtin_base: type[Exception]):
    assert issubclass(error, ClientXError)
    assert issubclass(error, builtin_base)


def test_clientx_error_catches_definition_time_errors():
    with pytest.raises(ClientXError):

        class API(ClientX):
            @get("/v1/items")
            def list_items(self): ...  # missing return annotation


def test_missing_return_type_message_names_clientx():
    def list_items(self): ...

    assert "ClientX requires an explicit return annotation" in str(MissingReturnTypeError(list_items))


def test_unconsumable_argument_message_points_to_the_request_part_helpers():
    message = str(UnconsumableArgumentError(field="token", annotation=str, value="abc"))

    assert "Annotated[..., Query()], Header(), Form(), Body(), File(), or Part(RequestPart.*)" in message
    assert "FieldX" not in message
    assert "RequestSection" not in message


def test_missing_path_arguments_error_still_catchable_as_value_error():
    with pytest.raises(ValueError, match="post_id"):
        raise MissingPathArgumentsError("/v1/posts/{post_id}", ["post_id"])
