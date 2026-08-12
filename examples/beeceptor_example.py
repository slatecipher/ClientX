from beeceptor import Beeceptor

import logging


def setup_logging() -> None:
    # Root stays quiet unless you want everything.
    logging.basicConfig(level=logging.WARNING)

    clientx_logger = logging.getLogger("clientx")
    clientx_logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)

    # Include the structured extra field `http` if ClientX provides it.
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)

    # Avoid duplicate logs if the root logger also has handlers.
    clientx_logger.propagate = False
    clientx_logger.handlers.clear()
    clientx_logger.addHandler(handler)


setup_logging()

# ClientX.setup_client wires an httpx2.Client with the base URL and default headers.
# Decorated API methods never run their bodies; ClientX builds the request from the
# signature, formats path params, and injects request parts from annotated inputs.

client = Beeceptor("https://fake-json-api.mock.beeceptor.com")

# Returns typed models because the endpoint declares a return type and decoder.
# If the return type were httpx2.Response, you'd receive the raw response instead see example below.
yahoo_users = [user for user in client.get_users() if user.email.endswith("yahoo.com")]

for user in yahoo_users:
    print(user.email)


# Another typed call; returns validated Company models for richer access.
companies = client.get_companies()

for comapny in companies:
    print(f"{comapny.name}: {comapny.employee_count:,} employees")


# Raw response example: return type is httpx2.Response, so no decoder runs.
# Use this path when you want direct access to status codes or response bodies.
response = client.get_companies_raw()

print(f"HTTP Status Code: {response.status_code}")

# Deprecated call example: this will emit a deprecation warning message.
response = client.get_companies_dep()

print(response)
