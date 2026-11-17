"""Exceptions raised by ClientX.

Every exception derives from ``ClientXError``, so ``except ClientXError`` catches them all.
Each also keeps a built-in base, so ``except TypeError`` handlers keep working.

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


__all__ = ["ClientXError", "DefinitionError"]
