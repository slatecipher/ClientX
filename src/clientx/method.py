"""The HTTP verb decorators that turn a client's methods into endpoints.

Use them as ``@method.get("/users")``.
"""

from clientx._method import Method

get = Method("GET")
post = Method("POST")
put = Method("PUT")
patch = Method("PATCH")
delete = Method("DELETE")
head = Method("HEAD")
options = Method("OPTIONS")

__all__ = ["delete", "get", "head", "options", "patch", "post", "put"]
