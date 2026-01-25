from beeceptor import Beeceptor

# ClientX.setup_client wires an httpx.Client with the base URL and default headers.
# Decorated API methods never run their bodies; ClientX builds the request from the
# signature, formats path params, and injects request parts from annotated inputs.

client = Beeceptor.setup_client("https://fake-json-api.mock.beeceptor.com")

# Returns typed models because the endpoint declares a return type and decoder.
# If the return type were httpx.Response, you'd receive the raw response instead see example below.
yahoo_users = [user for user in client.get_users() if user.email.endswith("yahoo.com")]

for user in yahoo_users:
    print(user.email)


# Another typed call; returns validated Company models for richer access.
companies = client.get_companies()

for comapny in companies:
    print(f"{comapny.name}: {comapny.employeeCount:,} employees")


# Raw response example: return type is httpx.Response, so no decoder runs.
# Use this path when you want direct access to status codes or response bodies.
response = client.get_companies_raw()

print(f"HTTP Status Code: {response.status_code}")

# Deprecated call example: this will emit a deprecation warning message.
response = client.get_companies_dep()

print(response)
