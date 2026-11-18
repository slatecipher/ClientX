"""Set up client and resource subclasses when they're defined.

``__init_subclass__`` on the bases in ``_client.py`` calls into this module, so
the rules that run once per class live here, apart from the classes themselves.
This module imports nothing from ``_client.py`` at runtime, so ``_client.py``
can import it without a circular import.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from functools import cache
from typing import TYPE_CHECKING

from clientx._registry import endpoint_for
from clientx.exceptions import DefinitionError

if TYPE_CHECKING:
    from clientx._client import AsyncClientX, AsyncResource, ClientX, Resource
    from clientx._endpoint import Endpoint

# The sync and the async base of each kind of class, by `__clientx_is_async__`,
# for error messages.
_CLIENT_BASES = ("ClientX", "AsyncClientX")
_RESOURCE_BASES = ("Resource", "AsyncResource")


def set_up_client(
    cls: type[ClientX | AsyncClientX], *, base: type[ClientX | AsyncClientX], user_agent: str | None
) -> None:
    """Set up a new client subclass: check its body and claim its endpoints.

    ``base`` is ``ClientX`` or ``AsyncClientX``, whose names the endpoints can't
    use. A subclass without its own ``user_agent`` keeps its parent's. Claiming
    the endpoints stops a resource from taking one and joining its prefix onto
    the client's path. Each endpoint's request plan is worked out once its path
    is final.
    """
    _check_one_kind(cls, _CLIENT_BASES)
    _check_member_names(cls, base, fix="Rename it, or put it on a Resource mounted on the client.")
    _check_endpoint_kinds(cls, _CLIENT_BASES)
    if user_agent is not None:
        cls.__clientx_user_agent__ = user_agent
    for endpoint in _claim_endpoints(cls):
        endpoint.set_up_request()


def set_up_resource(
    cls: type[Resource | AsyncResource],
    *,
    base: type[Resource | AsyncResource],
    prefix: str | None,
    tags: Sequence[str] | None,
) -> None:
    """Set up a new resource subclass: check it, and apply its prefix and tags.

    ``base`` is ``Resource`` or ``AsyncResource``, whose names the endpoints
    can't use. A subclass without its own ``prefix`` keeps its parent's, and its
    ``tags`` are added to its parent's, each tag once. The prefix is joined to
    each endpoint's path now, so it's absolute: it doesn't depend on where the
    resource is mounted. Each endpoint's request plan is worked out after the
    join, because the prefix can add placeholders.
    """
    _check_one_kind(cls, _RESOURCE_BASES)
    _check_member_names(cls, base, fix="Rename it.")
    _check_endpoint_kinds(cls, _RESOURCE_BASES)
    if prefix is not None:
        cls.__clientx_prefix__ = prefix
    if tags is not None:
        # Until now, `cls` inherits its parent's tags: add its own after them.
        cls.__clientx_tags__ = tuple(dict.fromkeys([*cls.__clientx_tags__, *tags]))
    for endpoint in _claim_endpoints(cls):
        endpoint.raw_path = _join_path(cls.__clientx_prefix__, endpoint.raw_path)
        endpoint.tags = list(dict.fromkeys([*cls.__clientx_tags__, *endpoint.tags]))
        endpoint.set_up_request()


def check_mount(resource_name: str, *, is_async: bool, owner: type) -> None:
    """Raise ``DefinitionError`` unless a resource's owner is its own kind.

    A resource's ``__set_name__`` calls it when an instance is assigned in
    ``owner``'s body. A ``Resource``'s ``def`` endpoints need a ``ClientX`` to
    send through, and an ``AsyncResource``'s ``async def`` endpoints an
    ``AsyncClientX``.
    """
    owner_kind = getattr(owner, "__clientx_is_async__", None)
    if owner_kind is is_async:
        return
    client, resource = _CLIENT_BASES[is_async], _RESOURCE_BASES[is_async]
    message = (
        f"{resource} '{resource_name}' can only be mounted on a{'n' if is_async else ''} {client} or "
        f"{resource} subclass, not on '{owner.__qualname__}'."
    )
    if owner_kind is not None:
        other_client, other_resource = _CLIENT_BASES[not is_async], _RESOURCE_BASES[not is_async]
        message += f" For {'a' if is_async else 'an'} {other_client}, subclass {other_resource} instead."
    raise DefinitionError(message)


def _check_one_kind(cls: type, bases: tuple[str, str]) -> None:
    """Raise ``DefinitionError`` if ``cls`` has both a sync and an async base.

    Each base, such as ``ClientX`` or ``AsyncClientX``, sets
    ``__clientx_is_async__`` in its own body, so a class that inherits both has
    both values among the classes in its MRO.
    """
    kinds = {vars(class_)["__clientx_is_async__"] for class_ in cls.__mro__ if "__clientx_is_async__" in vars(class_)}
    if len(kinds) > 1:
        raise DefinitionError(f"'{cls.__qualname__}' can't subclass both {bases[0]} and {bases[1]}: choose one.")


def _check_endpoint_kinds(cls: type[ClientX | AsyncClientX | Resource | AsyncResource], bases: tuple[str, str]) -> None:
    """Raise ``DefinitionError`` if an endpoint is the wrong kind for ``cls``.

    ``ClientX`` and ``Resource`` send with a sync ``httpx2.Client``, so their
    endpoints are ``def`` methods; ``AsyncClientX`` and ``AsyncResource``
    endpoints are ``async def`` methods. Endpoints inherited from a parent class
    were checked when it was defined.
    """
    is_async = cls.__clientx_is_async__
    for value in vars(cls).values():
        endpoint = endpoint_for(value)
        if endpoint is not None and endpoint.signature.is_async != is_async:
            kind, fix = ("`async def`", "`def`") if endpoint.signature.is_async else ("a plain `def`", "`async def`")
            raise DefinitionError(
                f"Endpoint '{endpoint.signature.qualname}' is {kind}, so it can't be an endpoint of "
                f"'{cls.__qualname__}', a{'n' if is_async else ''} {bases[is_async]} subclass. "
                f"Define it with {fix}, or subclass {bases[not is_async]} instead."
            )


def _check_member_names(cls: type, base: type, *, fix: str) -> None:
    """Raise ``DefinitionError`` if an endpoint or resource has a reserved name.

    Overriding one breaks the client: an endpoint named ``send`` would replace
    the ``httpx2.Client.send`` that every request goes through. Other members,
    such as the subclass's own ``__init__``, may override ``base``'s names as
    usual.
    """
    reserved = _reserved_names(base)
    for name, value in vars(cls).items():
        if name in reserved and (endpoint_for(value) is not None or _is_resource(value)):
            raise DefinitionError(
                f"'{cls.__qualname__}.{name}' (defined in {cls.__module__}) can't be named '{name}': "
                f"{base.__name__} already uses that name, and overriding it breaks the client. {fix}"
            )


@cache
def _reserved_names(base: type) -> frozenset[str]:
    """Return the names endpoints and mounted resources can't use on ``base``.

    That's everything it defines: ``dir(base)``, which for a client includes all
    of ``httpx2.Client``'s names, plus the instance attributes ``base`` and its
    parents declare.
    """
    return frozenset(dir(base)).union(*(inspect.get_annotations(cls) for cls in base.__mro__))


def _is_resource(value: object) -> bool:
    """Return whether ``value`` is a mounted resource.

    Only resource classes define ``__clientx_prefix__``, so this module needn't
    import them. It's looked up on the type, so an object whose ``__getattr__``
    answers any name doesn't count.
    """
    return hasattr(type(value), "__clientx_prefix__")


def _claim_endpoints(cls: type) -> list[Endpoint]:
    """Make ``cls`` the owner of the endpoints in its body, and return them.

    A second name for an endpoint in the same body (an alias,
    ``QueryDevices = query_devices``) is the same endpoint, so a resource joins
    its prefix once. An endpoint that another class's body already has raises
    ``DefinitionError``: a resource would join its prefix onto that endpoint's
    path too, and an endpoint has one path.
    """
    claimed: list[Endpoint] = []
    for value in vars(cls).values():
        endpoint = endpoint_for(value)
        if endpoint is None or endpoint.owner is cls:
            continue
        if endpoint.owner is not None:
            raise DefinitionError(
                f"Endpoint '{endpoint.signature.qualname}' belongs to '{endpoint.owner.__qualname__}', so it can't "
                f"also be an endpoint of '{cls.__qualname__}': an endpoint has one path. Declare it in "
                f"'{cls.__qualname__}' too."
            )
        endpoint.owner = cls
        claimed.append(endpoint)
    return claimed


def _join_path(prefix: str, path: str) -> str:
    if not prefix:
        return path
    if not path:
        return prefix
    return prefix.rstrip("/") + "/" + path.lstrip("/")
