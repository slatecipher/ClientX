from clientx import ClientX, Response, method


class FilesAPI(ClientX):
    @method.get("/files/{file_id}", stream=True)
    def download(self, file_id: str) -> Response: ...


with FilesAPI("https://api.example.com") as api:
    response = api.download("42")
    try:
        with open("file.bin", "wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)
    finally:
        response.close()
