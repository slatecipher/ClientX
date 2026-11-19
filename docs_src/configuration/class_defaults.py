from clientx import ClientX


class ExampleAPI(ClientX, base_url="https://api.example.com", user_agent="example-api/1.0"): ...


api = ExampleAPI()  # https://api.example.com, User-Agent: example-api/1.0
staging = ExampleAPI("https://staging.example.com")
