from clientx._decorators import method

get = method.get
post = method.post
put = method.put
patch = method.patch
delete = method.delete
head = method.head
options = method.options

__all__ = ["delete", "get", "head", "options", "patch", "post", "put", "method"]
