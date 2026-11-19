from clientx import ClientX, Response, method


class FilesAPI(ClientX):
    @method.get("/files/{name}", raise_for_status=False)
    def get_file(self, name: str) -> Response:
        """Return a 404 as a response instead of raising, so the caller can check `status_code`."""
        ...


api = FilesAPI("https://api.example.com")  # every other endpoint still raises
unchecked = FilesAPI("https://api.example.com", raise_for_status=False)  # no endpoint raises
