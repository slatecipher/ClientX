# Error Rules

ClientX raises explicit errors for common contract violations. Most of them are raised when the class is defined, so a broken endpoint fails on import, not on its first call:

- missing return annotation -> `MissingReturnTypeError`
- typed return without decoder -> `MissingDecoderError`
- endpoint or mounted resource named like something `ClientX` already has (`close`, or a dunder method) -> `EndpointNameConflictError`
- path placeholder, including one from a resource prefix, that names no parameter -> `MissingPathArgumentsError`
- path placeholder with a converter other than `{name:path}` -> `PathTemplateError`
- no positional first parameter for the client (usually `self`, but any name works), a `*args` or `**kwargs` parameter, or a `PathParam()` parameter with no placeholder in the path (including a resource prefix) -> `EndpointSignatureError`
- request-part helper nested inside another type, two helpers on one parameter or field, or `PathParam()` on a model field -> `MisplacedHelperError` (for a model field, when the class is defined if a parameter is annotated with the model, or else when the model is sent)

At call time:

- endpoint called on a resource that isn't mounted on a client -> `UnboundResourceError`
- path value that's `None` or empty, or a `{name:path}` value with a leading, trailing, or doubled slash -> `PathValueError`
- argument cannot map to request parts, or a model field marked `Body()` or `File()` holds something other than a mapping or a model -> `UnconsumableArgumentError`
- argument doesn't match its annotation, when `validate_arguments` is on -> `ArgumentValidationError`

Annotations are evaluated when the class is defined, so endpoints work in modules with `from __future__ import annotations`. Like `pydantic`, ClientX evaluates them against the module's globals: a type defined inside a function can't be named in a string annotation.

All of them derive from `ClientXError` (importable from `clientx`), so `except ClientXError` catches any of them. Each also keeps its built-in base (`TypeError` or `ValueError`).

HTTP errors come from httpx2: connection errors and timeouts, and `HTTPStatusError` for 4xx and 5xx responses unless it's turned off (see [Raising errors for 4xx and 5xx responses](configuration.md#raising-errors-for-4xx-and-5xx-responses)).
