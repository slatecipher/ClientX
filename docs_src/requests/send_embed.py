from typing import Annotated

from clientx import ClientX, Json, Query, Response, Send, method


class HostsAPI(ClientX):
    @method.post("/devices/actions")
    def contain(
        self,
        action_name: Annotated[str, Query()],
        ids: Annotated[list[str], Json(), Send(embed=True)],
    ) -> Response: ...
