"""Experimental: request-part helpers built on ``pydantic.Field``.

Each helper takes exactly the arguments of ``pydantic.Field`` and returns its ``FieldInfo``, marked with the
part of the request it goes to. On an endpoint parameter, put the helper inside ``Annotated``. ClientX reads
it only there, by design: a helper given as a parameter's default value isn't read::

    class UsersAPI(ClientX):
        @method.post("/users")
        def create(
            self,
            username: Annotated[str, Json(min_length=3)],
            dry_run: Annotated[bool, Query()] = False,
        ) -> None: ...

A model field can carry a helper too, as its default or inside ``Annotated``, and ``get_argument_location``
reads the mark back::

    class CreateUserRequest(BaseModel):
        username: Annotated[str, Json(min_length=3)]
        dry_run: bool = Query(default=False)

    get_argument_location(CreateUserRequest.model_fields["dry_run"])
    # <HttpxArgument.PARAMS: 'params'>

The helpers align one-to-one with the arguments of ``httpx2.Client.build_request`` that carry request data
(every argument except ``method``, ``timeout``, ``extensions`` and ``cookies``), so ``Body`` is httpx's raw
``content`` and ``Json`` its ``json``. There's no ``Cookie`` helper: httpx2 is deprecating per-request cookies,
so set cookies on the client instead. Each helper, and the argument it marks:

    ``Url``     ``url``
    ``Query``   ``params``
    ``Header``  ``headers``
    ``Body``    ``content``, the raw body
    ``Form``    ``data``
    ``File``    ``files``
    ``Json``    ``json``

Known limitation, on model fields only: type checkers treat only ``pydantic.Field`` itself as a field
specifier (Pydantic's ``dataclass_transform``), so they don't see a helper's alias, whether it's the default
or inside ``Annotated``. With ``Query(alias="timeStamp")``, pyright accepts ``Model(timestamp=...)``, which
fails at runtime, and rejects ``Model(timeStamp=...)``, which works. ``serialization_alias`` avoids this,
since the field is then created by its own name. A helper as the default also makes the field look optional
to them; inside ``Annotated`` it doesn't. Endpoint parameters are ordinary parameters, so type checkers
check them as usual.
"""

from pydantic import Field

from clientx._arguments import HttpxArgument, bind_argument, get_argument_location

Url = bind_argument("Url", HttpxArgument.URL, Field)
Query = bind_argument("Query", HttpxArgument.PARAMS, Field)
Header = bind_argument("Header", HttpxArgument.HEADERS, Field)
Body = bind_argument("Body", HttpxArgument.CONTENT, Field)
Form = bind_argument("Form", HttpxArgument.DATA, Field)
File = bind_argument("File", HttpxArgument.FILES, Field)
Json = bind_argument("Json", HttpxArgument.JSON, Field)

__all__ = ["Body", "File", "Form", "Header", "HttpxArgument", "Json", "Query", "Url", "get_argument_location"]
