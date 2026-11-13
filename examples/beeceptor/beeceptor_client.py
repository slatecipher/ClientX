from __future__ import annotations

from typing import Annotated

from clientx import ClientX, DeprecatedMessage, PathParam, Resource, Response, method
from clientx.decoders import ModelDecoder, TypeAdapterDecoder

from .beeceptor_models import Companies, Company, User, Users


class UsersResource(Resource, prefix="/users"):
    """Beeceptor's sample users, under ``/users``."""

    @method.get(decoder=TypeAdapterDecoder(Users))
    def list_all(self) -> list[User]:
        """Return Beeceptor sample users as `User` models.

        The endpoint responds with a JSON array of user profiles (id, name,
        company, username, email, address, zip, state, country, phone, photo),
        which the client validates and returns as a typed list for demos or
        quick integration tests.
        """
        ...

    @method.get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: Annotated[int, PathParam(description="The user's ID.")]) -> User:
        """Return one Beeceptor sample user as a `User` model.

        `user_id` fills the `{user_id}` placeholder in the path, so
        `retrieve(1)` requests `/users/1`.
        """
        ...


class CompaniesResource(Resource, prefix="/companies"):
    """Beeceptor's sample companies, under ``/companies``."""

    @method.get(decoder=TypeAdapterDecoder(Companies))
    def list_all(self) -> list[Company]:
        """Return Beeceptor sample companies as `Company` models.

        The endpoint responds with a JSON array of company records (id, name,
        address, zip, country, employeeCount, industry, marketCap, domain,
        logo, ceoName), which the client validates and returns as a typed
        list for demos or quick integration tests.
        """
        ...

    @method.get()
    def list_raw(self) -> Response:
        """Return the raw Beeceptor companies response.

        The endpoint responds with a JSON array of company records. This method
        returns the unvalidated Response for demos or quick integration tests.
        """
        ...

    @method.get(
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


class Beeceptor(ClientX, base_url="https://fake-json-api.mock.beeceptor.com", user_agent="beeceptor-example/0.1"):
    """Client for Beeceptor's hosted sample API to validate ClientX flows.

    Beeceptor provides mock servers you can configure with custom paths,
    methods, and responses, plus pre-built sample APIs for common scenarios.
    The class arguments set the sample API's URL and this example's User-Agent, so
    `Beeceptor()` needs no arguments. To use your own mock server, create an endpoint
    in the Beeceptor web UI and pass its URL: `Beeceptor("https://<name>.mock.beeceptor.com")`.

    The endpoints are grouped into resources, which share this client's
    connection: `client.users.retrieve(1)`, `client.companies.list_all()`.

    Reference: https://beeceptor.com/docs/sample-api-for-testing/
    """

    users = UsersResource()
    companies = CompaniesResource()
