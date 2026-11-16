"""Experimental: request-part helpers built on ``pydantic.Field``.

Each helper takes exactly the arguments of ``pydantic.Field`` and returns its ``FieldInfo``, marked with the
part of the request the field goes to. ``get_argument_location`` reads the mark back::

    class CreateUserRequest(BaseModel):
        dry_run: bool = Query(default=False)
        username: str = Json(min_length=3)

    get_argument_location(CreateUserRequest.model_fields["dry_run"])
    # <HttpxArgument.PARAMS: 'params'>

The helpers align one-to-one with the arguments of ``httpx2.Client.build_request`` that carry request data
(every argument except ``method``, ``timeout``, and ``extensions``), so ``Body`` is httpx's raw ``content``
and ``Json`` its ``json``. This is a separate experiment from ClientX's own helpers, where ``Body()`` is the
JSON body. Each helper, and the argument it marks a field for:

    ``Url``     ``url``
    ``Query``   ``params``
    ``Header``  ``headers``
    ``Cookie``  ``cookies``
    ``Body``    ``content``, the raw body
    ``Form``    ``data``
    ``File``    ``files``
    ``Json``    ``json``

Known limitation: type checkers treat only ``pydantic.Field`` itself as a field specifier (Pydantic's
``dataclass_transform``), so they read a helper's result as a plain default value. Every field then looks
optional to them, and they don't see aliases: with ``Query(alias="timeStamp")``, pyright accepts
``Model(timestamp=...)``, which fails at runtime, and rejects ``Model(timeStamp=...)``, which works.
``serialization_alias`` avoids the alias half, since the field is then created by its own name.
"""

from pydantic import Field

from clientx._arguments import HttpxArgument, bind_argument, get_argument_location

Url = bind_argument("Url", HttpxArgument.URL, Field)
Query = bind_argument("Query", HttpxArgument.PARAMS, Field)
Header = bind_argument("Header", HttpxArgument.HEADERS, Field)
Cookie = bind_argument("Cookie", HttpxArgument.COOKIES, Field)
Body = bind_argument("Body", HttpxArgument.CONTENT, Field)
Form = bind_argument("Form", HttpxArgument.DATA, Field)
File = bind_argument("File", HttpxArgument.FILES, Field)
Json = bind_argument("Json", HttpxArgument.JSON, Field)

__all__ = ["Body", "Cookie", "File", "Form", "Header", "HttpxArgument", "Json", "Query", "Url", "get_argument_location"]
