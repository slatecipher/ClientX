from importlib.metadata import version

__version__ = version("clientx")

from httpx import Response

from clientx.client import ClientX
from clientx.decorators import api, endpoints
from clientx.endpoint_context import Deprecated

__all__ = ["api", "endpoints", "ClientX", "Deprecated", "Response"]
