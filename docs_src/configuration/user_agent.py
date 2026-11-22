from clientx import ClientX


class ExampleAPI(ClientX, base_url="https://api.example.com", user_agent="example-client/0.1"): ...


api = ExampleAPI(user_agent="my-app/1.0 (me@example.com)")
print(api.headers["User-Agent"])  # my-app/1.0 (me@example.com) example-client/0.1 ClientX/<version>

api.headers["User-Agent"] = "my-app/1.0"  # sent as it is
