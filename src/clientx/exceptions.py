"""Exceptions raised by ClientX.

Every exception derives from ``ClientXError``, so ``except ClientXError`` catches them all.
Each also keeps a built-in base, so ``except TypeError`` and ``except ValueError`` handlers
keep working.

HTTP errors aren't wrapped: connection errors, timeouts, and ``httpx2.HTTPStatusError``
for 4xx and 5xx responses come from httpx2.
"""


class ClientXError(Exception):
    """Base class for every exception ClientX raises."""


class DefinitionError(ClientXError, TypeError):
    """Raised when a client, resource or endpoint is written in a way ClientX can't use.

    Almost all are raised when the class is defined, so a mistake fails when its module
    is imported, not on the first call. The message names the class or endpoint, and the
    fix. An endpoint called on a resource that isn't mounted on a client, or on an object
    that isn't a client, raises it at call time.
    """


class ArgumentError(ClientXError, ValueError):
    """Raised before a request is sent, when an argument's value can't be sent.

    For example, a path value that's ``None`` or empty: ``/users/{user_id}`` with ``""``
    would call ``/users/``, a different path. The message names the parameter and the problem.

    Attributes:
        parameter: The name of the endpoint parameter the value was passed for.
    """

    def __init__(self, message: str, *, parameter: str) -> None:
        """Store the message and the parameter's name."""
        super().__init__(message)
        self.parameter = parameter


__all__ = ["ArgumentError", "ClientXError", "DefinitionError"]
