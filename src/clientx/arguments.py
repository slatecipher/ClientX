"""Request-part helpers built on ``pydantic.Field``, exported by ``clientx``.

Each helper takes exactly the arguments of ``pydantic.Field`` and returns its
``FieldInfo``, marked with the part of the request it goes to. On an endpoint
parameter, put the helper inside ``Annotated``. ClientX reads it only there, by
design: a helper given as a parameter's default value isn't read, and a default
inside the helper raises ``DefinitionError``, so put it after ``=``::

    class UsersAPI(ClientX):
        @method.post("/users")
        def create(
            self,
            username: Annotated[str, Json(min_length=3)],
            dry_run: Annotated[bool, Query()] = False,
        ) -> None: ...

Every parameter needs a helper, except one named like a path placeholder,
which fills it. ClientX doesn't guess where a parameter goes: a parameter
without a helper raises ``DefinitionError``.

A ``Query()``, ``Header()`` or ``Form()`` helper on a model, dataclass or
mapping parameter sends each of its fields to that part: with
``filters: Annotated[Filters, Query()]``, each field of ``Filters`` is a query
parameter. A helper on a model's own field raises ``DefinitionError``, because
the parameter decides where all of its fields go.

The helpers align one-to-one with the arguments of
``httpx2.Client.build_request`` that carry request data (every argument except
``method``, ``timeout``, ``extensions`` and ``cookies``), so ``Body`` is httpx's
raw ``content`` and ``Json`` its ``json``. There's no ``Cookie`` helper: httpx2
is deprecating per-request cookies, so set cookies on the client instead. Each
helper, and the argument it marks:

    ``Url``     ``url``
    ``Query``   ``params``
    ``Header``  ``headers``
    ``Body``    ``content``, the raw body
    ``Form``    ``data``
    ``File``    ``files``
    ``Json``    ``json``

``Send`` changes how a parameter is sent, put next to its helper in
``Annotated``: ``ids: Annotated[list[str], Json(), Send(embed=True)]`` sends a
lone list as ``{"ids": [...]}`` rather than as the whole body.
"""

from pydantic import Field

from clientx._arguments import bind_argument
from clientx._types import HttpxArgument, Send

Url = bind_argument("Url", HttpxArgument.URL, Field)
Query = bind_argument("Query", HttpxArgument.PARAMS, Field)
Header = bind_argument("Header", HttpxArgument.HEADERS, Field)
Body = bind_argument("Body", HttpxArgument.CONTENT, Field)
Form = bind_argument("Form", HttpxArgument.DATA, Field)
File = bind_argument("File", HttpxArgument.FILES, Field)
Json = bind_argument("Json", HttpxArgument.JSON, Field)

__all__ = ["Body", "File", "Form", "Header", "Json", "Query", "Send", "Url"]
