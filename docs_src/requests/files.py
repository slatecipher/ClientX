from typing import Annotated

from clientx import ClientX, File, Form, Response, method


class ProfilesAPI(ClientX):
    @method.post("/profile/avatar")
    def upload_avatar(
        self,
        image: Annotated[tuple[str, bytes, str], File()],
        caption: Annotated[str, Form()] = "",
    ) -> Response: ...
