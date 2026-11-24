from typing import Any

from clientx import ClientX, method
from clientx.tools import list_tools


class RouterAPI(ClientX, base_url="https://router.example.com/api"):
    @method.get("/status")
    def status(self) -> dict[str, Any]:
        """Fetch the router's status: its uptime, and the devices connected."""
        ...

    # The configuration holds the admin password's hash and the Wi-Fi keys.
    @method.get("/config", include_in_tools=False)
    def config(self) -> dict[str, Any]:
        """Export the whole configuration, to back it up."""
        ...


api = RouterAPI()
print([each.name for each in list_tools(api)])  # ['status']
