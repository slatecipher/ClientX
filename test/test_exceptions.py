from clientx.exceptions import UnprocessedArgumentsError


def test_unprocessed_arguments_error_exposes_leftovers_and_message():
    leftovers = {"x": 1, "y": "two"}

    err = UnprocessedArgumentsError(leftovers)

    assert err.leftovers == leftovers
    assert str(err) == "Unprocessed arguments: x=1, y='two'"
