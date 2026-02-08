from clientx import methods
from clientx._decorators import method as decorated_method


def test_methods_module_exposes_http_verb_aliases():
    assert methods.method is decorated_method
    assert methods.get is decorated_method.get
    assert methods.post is decorated_method.post
    assert methods.put is decorated_method.put
    assert methods.patch is decorated_method.patch
    assert methods.delete is decorated_method.delete
    assert methods.head is decorated_method.head
    assert methods.options is decorated_method.options
