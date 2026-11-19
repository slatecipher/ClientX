from typing import Annotated

from clientx import Body, ClientX, Header, Response, method


class NotesAPI(ClientX):
    @method.put("/notes/{note_id}")
    def save(
        self,
        note_id: int,
        text: Annotated[str, Body()],
        content_type: Annotated[str, Header(alias="Content-Type")] = "text/markdown",
    ) -> Response: ...
