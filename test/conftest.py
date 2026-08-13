import pytest

from clientx._endpoint_context import EndpointRegister


@pytest.fixture(autouse=True)
def reset_endpoint_registry():
    """Isolate each test from the process-wide endpoint registry.

    `EndpointRegister.registry` is a `ClassVar` populated as a side effect of
    applying the HTTP verb decorators, so any test that defines a decorated
    client class mutates state shared by the whole session. Clearing the list
    before each test lets tests assert on exact registry contents; restoring the
    original afterwards keeps import-time registrations intact for anything that
    runs later.
    """
    original = list(EndpointRegister.registry)
    EndpointRegister.registry = []
    try:
        yield
    finally:
        EndpointRegister.registry = original
