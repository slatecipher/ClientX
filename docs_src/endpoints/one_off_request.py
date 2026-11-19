from clientx import ClientX


class ExampleAPI(ClientX): ...


with ExampleAPI("https://api.example.com") as api:
    response = api.get("/status")
    response.raise_for_status()
