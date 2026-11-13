"""The HTTP verb decorators: ``get``, ``post``, ``put``, ``patch``, ``delete``, ``head`` and ``options``.

Import the module and decorate endpoints with ``@method.get(...)``::

    from clientx import ClientX, method

    class ExampleAPI(ClientX):
        @method.get("/health")
        def health(self) -> Response: ...

An endpoint named like a decorator, such as ``get``, can't hide ``method.get``. Importing the
decorators themselves, ``from clientx.method import get``, works too, as long as no endpoint in
the class is named like one: it would replace the decorator for the rest of the class body.
"""

from clientx._decorators import ApiMethod

get = ApiMethod("GET")
post = ApiMethod("POST")
put = ApiMethod("PUT")
patch = ApiMethod("PATCH")
delete = ApiMethod("DELETE")
head = ApiMethod("HEAD")
options = ApiMethod("OPTIONS")

__all__ = ["delete", "get", "head", "options", "patch", "post", "put"]
