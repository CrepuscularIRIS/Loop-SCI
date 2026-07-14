"""loop_sci.literature.search — unified search schema, client protocol and transport boundary."""

from .schema import PaperResult
from .client import SearchClient, make_async_client

__all__ = ["PaperResult", "SearchClient", "make_async_client"]
