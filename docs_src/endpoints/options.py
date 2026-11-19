from clientx import ClientX, Response, method


class FilesAPI(ClientX):
    @method.get("/files/{name}", timeout=60.0, raise_for_status=False)
    def download(self, name: str) -> Response:
        """Fetch a file. A 404 is returned as a response instead of raising."""
        ...
