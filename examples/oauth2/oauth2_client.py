from clientx import ClientX, method
from clientx.decoders import TypeAdapterDecoder
from pydantic import BaseModel, TypeAdapter

DEMO_URL = "https://demo.duendesoftware.com"
TOKEN_URL = f"{DEMO_URL}/connect/token"


class Claim(BaseModel):
    """One claim from an access token, such as the client ID or the scope."""

    type: str
    value: str


class DemoAPI(ClientX, base_url=DEMO_URL, user_agent="oauth2-example/0.1"):
    """Client for the API on Duende's public IdentityServer demo (https://demo.duendesoftware.com).

    Every call needs a bearer token from the demo's token endpoint, `TOKEN_URL`: pass
    `auth=ClientCredentials(TOKEN_URL, ...)` when creating the client.
    """

    @method.get("/api/test", decoder=TypeAdapterDecoder(TypeAdapter(list[Claim])))
    def claims(self) -> list[Claim]:
        """Return the claims of the access token the API received."""
        ...
