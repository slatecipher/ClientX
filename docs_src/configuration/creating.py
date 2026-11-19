from clientx import ClientX


class ExampleAPI(ClientX): ...


api = ExampleAPI("https://api.example.com", user_agent="my-app/1.0", timeout=5.0)
