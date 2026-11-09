import logging

from beeceptor import Beeceptor


def main() -> None:
    # Print a line for each endpoint call; ClientX logs them on the `clientx` logger at DEBUG level.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("clientx").setLevel(logging.DEBUG)

    # Endpoint method bodies never run. ClientX builds each request from the method's
    # signature and decorator: it fills path placeholders and maps the arguments to
    # request parts. `user_agent` sets the User-Agent header for every request, and
    # `with` closes the client's connections when the block ends.
    with Beeceptor("https://fake-json-api.mock.beeceptor.com", user_agent="beeceptor-example/0.1") as client:
        # Returns typed models because the endpoint declares a return type and a decoder.
        # An endpoint annotated `-> Response` returns the raw response instead (see below).
        yahoo_users = [user for user in client.get_users() if user.email.endswith("yahoo.com")]

        for user in yahoo_users:
            print(user.email)

        # Path parameter: `user_id` fills the `{user_id}` placeholder, so this requests /users/1.
        user = client.get_user(1)

        print(f"User 1: {user.name} ({user.email})")

        # Another typed call; returns validated Company models for richer access.
        companies = client.get_companies()

        for company in companies:
            print(f"{company.name}: {company.employee_count:,} employees")

        # Raw response example: the return type is httpx2.Response, so no decoder runs.
        # Use this when you want direct access to status codes or response bodies.
        response = client.get_companies_raw()

        print(f"HTTP Status Code: {response.status_code}")

        # Deprecated call example: this emits a DeprecationWarning.
        response = client.get_companies_dep()

        print(response)


if __name__ == "__main__":
    main()
