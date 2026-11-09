from __future__ import annotations

from clientx import ClientX, DeprecatedMessage, Response
from clientx.decoders import ModelDecoder, TypeAdapterDecoder
from clientx.methods import get

from .beeceptor_models import Companies, Company, User, Users


class Beeceptor(ClientX):
    """Client for Beeceptor's hosted sample API to validate ClientX flows.

    Beeceptor provides mock servers you can configure with custom paths,
    methods, and responses, plus pre-built sample APIs for common scenarios.
    Use the Beeceptor web UI to create an endpoint, define the response format,
    and then plug the endpoint URL into this client for fast integration tests.

    Reference: https://beeceptor.com/docs/sample-api-for-testing/
    """

    @get("/users", decoder=TypeAdapterDecoder(Users))
    def get_users(self) -> list[User]:
        """Return Beeceptor sample users as `User` models.

        The endpoint responds with a JSON array of user profiles (id, name,
        company, username, email, address, zip, state, country, phone, photo),
        which the client validates and returns as a typed list for demos or
        quick integration tests.
        """
        ...

    @get("/users/{user_id}", decoder=ModelDecoder(User))
    def get_user(self, user_id: int) -> User:
        """Return one Beeceptor sample user as a `User` model.

        `user_id` fills the `{user_id}` placeholder in the path, so
        `get_user(1)` requests `/users/1`.
        """
        ...

    @get("/companies", decoder=TypeAdapterDecoder(Companies))
    def get_companies(self) -> list[Company]:
        """Return Beeceptor sample companies as `Company` models.

        The endpoint responds with a JSON array of company records (id, name,
        address, zip, country, employeeCount, industry, marketCap, domain,
        logo, ceoName), which the client validates and returns as a typed
        list for demos or quick integration tests.
        """
        ...

    @get("/companies")
    def get_companies_raw(self) -> Response:
        """Return the raw Beeceptor companies response.

        The endpoint responds with a JSON array of company records (id, name,
        address, zip, country, employeeCount, industry, marketCap, domain,
        logo, ceoName). This method returns the unvalidated Response for
        demos or quick integration tests.
        """
        ...

    @get(
        "/companies",
        deprecated=DeprecatedMessage(
            "Deprecated: use get_companies_raw(); this endpoint will be removed in a future release."
        ),
    )
    def get_companies_dep(self) -> Response:
        """Deprecated: return the raw Beeceptor companies response.

        The endpoint responds with a JSON array of company records (id, name,
        address, zip, country, employeeCount, industry, marketCap, domain,
        logo, ceoName). Use `get_companies_raw` for the same unvalidated
        Response payload.
        """
        ...
