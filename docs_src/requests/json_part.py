from typing import Annotated

from clientx import ClientX, File, Form, Response, Send, method
from pydantic import BaseModel


class Message(BaseModel):
    content: str


class MessagesAPI(ClientX):
    @method.post("/channels/{channel_id}/messages")
    def send_message(
        self,
        channel_id: int,
        message: Annotated[Message, Form(alias="payload_json"), Send(json_part=True)],
        attachments: Annotated[list[tuple[str, bytes]] | None, File()] = None,
    ) -> Response: ...
