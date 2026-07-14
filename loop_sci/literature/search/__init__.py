"""loop_sci.literature.search — unified search schema, client protocol and transport boundary."""

from .schema import PaperResult
from .client import SearchClient, make_async_client
from .semantic_scholar import SemanticScholarClient
from .arxiv import ArxivClient
from .pubmed import PubMedClient

__all__ = [
    "PaperResult",
    "SearchClient",
    "make_async_client",
    "SemanticScholarClient",
    "ArxivClient",
    "PubMedClient",
]
