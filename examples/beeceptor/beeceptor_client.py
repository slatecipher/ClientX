from __future__ import annotations

from .beeceptor_models import Companies, Company, User, Users

from clientx import ClientX, Response, api as x


class Beeceptor(ClientX):
    """Client for Beeceptor's hosted sample API to validate ClientX flows.

    Beeceptor provides mock servers you can configure with custom paths,
    methods, and responses, plus pre-built sample APIs for common scenarios.
    Use the Beeceptor web UI to create an endpoint, define the response format,
    and then plug the endpoint URL into this client for fast integration tests.

    Refernce: https://beeceptor.com/docs/sample-api-for-testing/
    """

    @x.get("/users", decoder=lambda r: Users.validate_python(r.json()))
    def get_users(self) -> list[User]:
        """Return Beeceptor sample users as `User` models.

        The endpoint responds with a JSON array of user profiles (id, name,
        company, username, email, address, zip, state, country, phone, photo),
        which the client validates and returns as a typed list for demos or
        quick integration tests.
        """
        ...

    @x.get("/companies", decoder=lambda r: Companies.validate_python(r.json()))
    def get_companies(self) -> list[Company]:
        """Return Beeceptor sample companies as `Company` models.

        The endpoint responds with a JSON array of company records (id, name,
        address, zip, country, employeeCount, industry, marketCap, domain,
        logo, ceoName), which the client validates and returns as a typed
        list for demos or quick integration tests.
        """
        ...

    @x.get("/companies")
    def get_companies_raw(self) -> Response:
        """Return Beeceptor sample companies as `Company` models.

        The endpoint responds with a JSON array of company records (id, name,
        address, zip, country, employeeCount, industry, marketCap, domain,
        logo, ceoName), which the client validates and returns as a typed
        list for demos or quick integration tests.
        """
        ...
