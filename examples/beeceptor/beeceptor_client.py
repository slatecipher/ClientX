from __future__ import annotations

from clientx import ClientX, DeprecatedMessage, Resource, Response
from clientx.decoders import ModelDecoder, TypeAdapterDecoder
from clientx.methods import get

from .beeceptor_models import Companies, Company, User, Users


class UsersResource(Resource, prefix="/users"):
    """Beeceptor's sample users, under ``/users``."""

    @get("", decoder=TypeAdapterDecoder(Users))
    def list_all(self) -> list[User]:
        """Return Beeceptor sample users as `User` models.

        The endpoint responds with a JSON array of user profiles (id, name,
        company, username, email, address, zip, state, country, phone, photo),
        which the client validates and returns as a typed list for demos or
        quick integration tests.
        """
        ...

    @get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: int) -> User:
        """Return one Beeceptor sample user as a `User` model.

        `user_id` fills the `{user_id}` placeholder in the path, so
        `retrieve(1)` requests `/users/1`.
        """
        ...


class CompaniesResource(Resource, prefix="/companies"):
    """Beeceptor's sample companies, under ``/companies``."""

    @get("", decoder=TypeAdapterDecoder(Companies))
    def list_all(self) -> list[Company]:
        """Return Beeceptor sample companies as `Company` models.

        The endpoint responds with a JSON array of company records (id, name,
        address, zip, country, employeeCount, industry, marketCap, domain,
        logo, ceoName), which the client validates and returns as a typed
        list for demos or quick integration tests.
        """
        ...

    @get("")
    def list_raw(self) -> Response:
        """Return the raw Beeceptor companies response.

        The endpoint responds with a JSON array of company records. This method
        returns the unvalidated Response for demos or quick integration tests.
        """
        ...

    @get(
        "",
        deprecated=DeprecatedMessage(
            "Deprecated: use companies.list_raw(); this endpoint will be removed in a future release."
        ),
    )
    def list_deprecated(self) -> Response:
        """Deprecated: return the raw Beeceptor companies response.

        Use `list_raw` for the same unvalidated Response payload.
        """
        ...


class Beeceptor(ClientX):
    """Client for Beeceptor's hosted sample API to validate ClientX flows.

    Beeceptor provides mock servers you can configure with custom paths,
    methods, and responses, plus pre-built sample APIs for common scenarios.
    Use the Beeceptor web UI to create an endpoint, define the response format,
    and then plug the endpoint URL into this client for fast integration tests.

    The endpoints are grouped into resources, which share this client's
    connection: `client.users.retrieve(1)`, `client.companies.list_all()`.

    Reference: https://beeceptor.com/docs/sample-api-for-testing/
    """

    users = UsersResource()
    companies = CompaniesResource()
