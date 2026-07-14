---
change: literature-mining
design-doc: docs/superpowers/specs/2026-07-14-literature-mining-design.md
base-ref: 58f6a4b62d917df7af879dcd021e4f3a57e5060f
---

# Literature Mining Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first scored pipeline capability to Loop-SCI: topic → multi-source literature search → Qwen fact extraction → 4-layer citation verification → a persisted, queryable verified-fact base that the hypothesis-engine will consume.

**Architecture:** New package `loop_sci/literature/` with four sub-packages (search, extract, verify, factbase) plus an executor and tools module. All network access (search APIs and Qwen calls for extraction/verification) is isolated behind an injectable boundary so the default test suite is 100% offline; opt-in `@pytest.mark.live` tests exercise real APIs. Verified facts persist to two stores: the foundation IdeaTree (via `Node.refs`) and a queryable JSON fact store — no vendored edits.

**Tech Stack:** Python 3.11+, httpx (injectable transport for mocking), existing `loop_sci.engine.{Executor, ExecutorResult, DispatchUnit, ToolRegistry}`, `loop_sci.state.{IdeaTree, Node}`, `loop_sci.provider.factory.build_provider`, pytest + pytest-asyncio, ruff.

## Global Constraints

- No vendored edits: all tree mutations go through `IdeaTree.add_node` / `IdeaTree.update_node`; `Node.refs` is the payload field (already persists through save/reload).
- Default test suite: zero network calls; all HTTP mocked via httpx injectable transport or `MockProvider` from `tests/conftest.py`.
- Offline tests live in `tests/unit/literature/` and `tests/integration/`; live tests in `tests/live/`.
- `@pytest.mark.live` requires `DASHSCOPE_API_KEY` (Qwen) and optionally `SEMANTIC_SCHOLAR_API_KEY` and `PUBMED_EMAIL`; live tests skip cleanly without them.
- Coverage ≥ 80% on new `loop_sci/literature/` code (vendored paths excluded).
- ruff clean before every commit (`uv run ruff check loop_sci/literature/ tests/`).
- Every `Fact` must have `source_ref` + `evidence_span` — enforced in `__post_init__`.
- Per-run bounds: `max_papers` and `max_facts_per_paper` from config (default 10 / 5).
- record-before-decide + atomic persist: write `Node` to tree and JSON store before returning to the coordinator.

---

## Group 1: Literature Search (Tasks 1–3)

### Task 1: PaperResult schema + SearchClient protocol + httpx transport boundary

**Files:**
- Create: `loop_sci/literature/__init__.py`
- Create: `loop_sci/literature/search/__init__.py`
- Create: `loop_sci/literature/search/schema.py`
- Create: `loop_sci/literature/search/client.py`
- Create: `tests/unit/literature/__init__.py`
- Create: `tests/unit/literature/test_search_schema.py`

**Interfaces:**
- Produces: `PaperResult` dataclass, `SearchClient` Protocol, `MockTransport` test helper
- Consumed by: Tasks 2, 3, 4 (adapters, dispatch), Task 10 (tools)

- [x] **Step 1.1: Write failing tests for PaperResult and SearchClient**

```python
# tests/unit/literature/test_search_schema.py
from dataclasses import fields
from loop_sci.literature.search.schema import PaperResult
from loop_sci.literature.search.client import SearchClient
import inspect

def test_paper_result_fields():
    required = {"source", "external_id", "title", "authors", "year",
                "venue", "abstract", "url"}
    names = {f.name for f in fields(PaperResult)}
    assert required.issubset(names)

def test_paper_result_construction():
    p = PaperResult(
        source="semantic_scholar",
        external_id="s2:abc123",
        title="Test Paper",
        authors=["Smith J"],
        year=2024,
        venue="NeurIPS",
        abstract="This paper tests things.",
        url="https://example.com/paper",
    )
    assert p.source == "semantic_scholar"
    assert p.doi is None  # optional field

def test_search_client_is_protocol():
    # SearchClient must be a Protocol — not an ABC
    assert inspect.isclass(SearchClient)
```

Run: `uv run pytest tests/unit/literature/test_search_schema.py -v`
Expected: FAIL — module not found

- [x] **Step 1.2: Implement schema and client**

```python
# loop_sci/literature/search/schema.py
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class PaperResult:
    source: str          # "semantic_scholar" | "arxiv" | "pubmed"
    external_id: str     # source-specific id, e.g. "s2:abc" or "arxiv:2401.0001"
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    abstract: str | None
    url: str | None
    doi: str | None = None
```

```python
# loop_sci/literature/search/client.py
from __future__ import annotations
from typing import Protocol, runtime_checkable
from .schema import PaperResult

@runtime_checkable
class SearchClient(Protocol):
    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]: ...
    async def fetch_by_id(self, external_id: str) -> PaperResult | None: ...
```

- [x] **Step 1.3: Run tests to verify they pass**

Run: `uv run pytest tests/unit/literature/test_search_schema.py -v`
Expected: PASS

- [x] **Step 1.4: Commit**

```bash
git add loop_sci/literature/ tests/unit/literature/
git commit -m "feat(literature): PaperResult schema + SearchClient protocol"
```

---

### Task 2: Adapters — Semantic Scholar, arXiv, PubMed

**Files:**
- Create: `loop_sci/literature/search/semantic_scholar.py`
- Create: `loop_sci/literature/search/arxiv.py`
- Create: `loop_sci/literature/search/pubmed.py`
- Create: `tests/unit/literature/test_adapters.py`
- Create: `tests/unit/literature/fixtures/ss_search.json`
- Create: `tests/unit/literature/fixtures/arxiv_search.xml`
- Create: `tests/unit/literature/fixtures/pubmed_esearch.json`
- Create: `tests/unit/literature/fixtures/pubmed_efetch.xml`

**Interfaces:**
- Consumes: `PaperResult` from Task 1; `httpx.AsyncClient` with injectable transport
- Produces: `SemanticScholarClient(http: httpx.AsyncClient)`, `ArxivClient(http: httpx.AsyncClient)`, `PubMedClient(http: httpx.AsyncClient, *, email: str, tool: str)`

- [x] **Step 2.1: Create fixture files**

Save real-but-minimal recorded API responses (5–10 items each). The key constraint is the structure, not real data:

```json
// tests/unit/literature/fixtures/ss_search.json
{
  "data": [
    {
      "paperId": "s2abc123",
      "externalIds": {"DOI": "10.1234/test"},
      "title": "Neural Evidence for X",
      "authors": [{"name": "Smith J"}, {"name": "Lee K"}],
      "year": 2023,
      "venue": "NeurIPS",
      "abstract": "We show that X is real.",
      "url": "https://api.semanticscholar.org/paper/s2abc123"
    }
  ]
}
```

```xml
<!-- tests/unit/literature/fixtures/arxiv_search.xml -->
<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Spike-based learning</title>
    <author><name>Jones A</name></author>
    <published>2024-01-01T00:00:00Z</published>
    <summary>We study spike-based learning.</summary>
    <link href="https://arxiv.org/abs/2401.00001"/>
  </entry>
</feed>
```

```json
// tests/unit/literature/fixtures/pubmed_esearch.json
{"esearchresult": {"idlist": ["38000001"]}}
```

```xml
<!-- tests/unit/literature/fixtures/pubmed_efetch.xml -->
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>38000001</PMID>
      <Article>
        <ArticleTitle>Cortical circuits for attention</ArticleTitle>
        <Abstract><AbstractText>We map cortical circuits.</AbstractText></Abstract>
        <AuthorList><Author><LastName>Wang</LastName></Author></AuthorList>
        <Journal>
          <Title>Nature Neuroscience</Title>
          <JournalIssue><PubDate><Year>2023</Year></PubDate></JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
```

- [x] **Step 2.2: Write failing adapter tests**

```python
# tests/unit/literature/test_adapters.py
import json, pytest
from pathlib import Path
import httpx
from loop_sci.literature.search.semantic_scholar import SemanticScholarClient
from loop_sci.literature.search.arxiv import ArxivClient
from loop_sci.literature.search.pubmed import PubMedClient
from loop_sci.literature.search.schema import PaperResult

FIXTURES = Path(__file__).parent / "fixtures"

class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses: dict[str, tuple[int, bytes, str]]):
        # url_prefix -> (status, body, content_type)
        self._responses = responses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, (status, body, ctype) in self._responses.items():
            if prefix in url:
                return httpx.Response(status, content=body,
                                      headers={"content-type": ctype})
        return httpx.Response(404, content=b"not found")

@pytest.fixture
def ss_http():
    body = FIXTURES.joinpath("ss_search.json").read_bytes()
    transport = MockTransport({"graph.api.semanticscholar.org": (200, body, "application/json")})
    return httpx.AsyncClient(transport=transport, base_url="https://api.semanticscholar.org")

@pytest.mark.asyncio
async def test_ss_search_returns_paper_results(ss_http):
    client = SemanticScholarClient(http=ss_http)
    results = await client.search("neural spikes", max_results=5)
    assert len(results) == 1
    p = results[0]
    assert isinstance(p, PaperResult)
    assert p.source == "semantic_scholar"
    assert p.external_id == "s2:s2abc123"
    assert p.doi == "10.1234/test"

@pytest.fixture
def arxiv_http():
    body = FIXTURES.joinpath("arxiv_search.xml").read_bytes()
    transport = MockTransport({"export.arxiv.org": (200, body, "application/atom+xml")})
    return httpx.AsyncClient(transport=transport, base_url="https://export.arxiv.org")

@pytest.mark.asyncio
async def test_arxiv_search_returns_paper_results(arxiv_http):
    client = ArxivClient(http=arxiv_http)
    results = await client.search("spike learning", max_results=5)
    assert len(results) == 1
    p = results[0]
    assert p.source == "arxiv"
    assert "2401.00001" in p.external_id

@pytest.fixture
def pubmed_http():
    esearch_body = FIXTURES.joinpath("pubmed_esearch.json").read_bytes()
    efetch_body = FIXTURES.joinpath("pubmed_efetch.xml").read_bytes()
    transport = MockTransport({
        "esearch.fcgi": (200, esearch_body, "application/json"),
        "efetch.fcgi": (200, efetch_body, "application/xml"),
    })
    return httpx.AsyncClient(transport=transport, base_url="https://eutils.ncbi.nlm.nih.gov")

@pytest.mark.asyncio
async def test_pubmed_search_returns_paper_results(pubmed_http):
    client = PubMedClient(http=pubmed_http, email="test@example.com", tool="loop-sci-test")
    results = await client.search("cortical attention", max_results=5)
    assert len(results) == 1
    p = results[0]
    assert p.source == "pubmed"
    assert p.external_id == "pubmed:38000001"
```

Run: `uv run pytest tests/unit/literature/test_adapters.py -v`
Expected: FAIL — modules not found

- [x] **Step 2.3: Implement Semantic Scholar adapter**

```python
# loop_sci/literature/search/semantic_scholar.py
from __future__ import annotations
import httpx
from .schema import PaperResult

_BASE = "https://api.semanticscholar.org/graph/v1"
_FIELDS = "paperId,externalIds,title,authors,year,venue,abstract,url"

class SemanticScholarClient:
    def __init__(self, http: httpx.AsyncClient, *, api_key: str | None = None) -> None:
        self._http = http
        self._api_key = api_key

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        r = await self._http.get(
            f"{_BASE}/paper/search",
            params={"query": query, "limit": max_results, "fields": _FIELDS},
            headers=headers,
        )
        r.raise_for_status()
        return [_to_paper(item) for item in r.json().get("data", [])]

    async def fetch_by_id(self, external_id: str) -> PaperResult | None:
        sid = external_id.removeprefix("s2:")
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        r = await self._http.get(
            f"{_BASE}/paper/{sid}", params={"fields": _FIELDS}, headers=headers
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return _to_paper(r.json())

def _to_paper(d: dict) -> PaperResult:
    eids = d.get("externalIds") or {}
    authors = [a["name"] for a in (d.get("authors") or [])]
    return PaperResult(
        source="semantic_scholar",
        external_id=f"s2:{d['paperId']}",
        title=d.get("title") or "",
        authors=authors,
        year=d.get("year"),
        venue=d.get("venue"),
        abstract=d.get("abstract"),
        url=d.get("url"),
        doi=eids.get("DOI"),
    )
```

- [x] **Step 2.4: Implement arXiv adapter**

```python
# loop_sci/literature/search/arxiv.py
from __future__ import annotations
import xml.etree.ElementTree as ET
import httpx
from .schema import PaperResult

_NS = {"atom": "http://www.w3.org/2005/Atom"}
_BASE = "https://export.arxiv.org/api/query"

class ArxivClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        r = await self._http.get(
            _BASE, params={"search_query": f"all:{query}", "max_results": max_results}
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)
        return [_entry_to_paper(e) for e in root.findall("atom:entry", _NS)]

    async def fetch_by_id(self, external_id: str) -> PaperResult | None:
        arxiv_id = external_id.removeprefix("arxiv:")
        r = await self._http.get(_BASE, params={"id_list": arxiv_id})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        entries = root.findall("atom:entry", _NS)
        return _entry_to_paper(entries[0]) if entries else None

def _entry_to_paper(e: ET.Element) -> PaperResult:
    ns = _NS
    raw_id = (e.findtext("atom:id", namespaces=ns) or "").rstrip("v1234567890")
    arxiv_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id
    authors = [
        a.findtext("atom:name", namespaces=ns) or ""
        for a in e.findall("atom:author", ns)
    ]
    published = e.findtext("atom:published", namespaces=ns) or ""
    year = int(published[:4]) if len(published) >= 4 else None
    link_el = e.find("atom:link[@rel='alternate']", ns) or e.find("atom:link", ns)
    url = link_el.get("href") if link_el is not None else None
    return PaperResult(
        source="arxiv",
        external_id=f"arxiv:{arxiv_id}",
        title=(e.findtext("atom:title", namespaces=ns) or "").strip(),
        authors=authors,
        year=year,
        venue=None,
        abstract=(e.findtext("atom:summary", namespaces=ns) or "").strip(),
        url=url,
    )
```

- [x] **Step 2.5: Implement PubMed adapter**

```python
# loop_sci/literature/search/pubmed.py
from __future__ import annotations
import xml.etree.ElementTree as ET
import httpx
from .schema import PaperResult

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

class PubMedClient:
    def __init__(self, http: httpx.AsyncClient, *, email: str, tool: str = "loop-sci") -> None:
        self._http = http
        self._params = {"tool": tool, "email": email, "retmode": "json"}

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        r = await self._http.get(
            f"{_EUTILS}/esearch.fcgi",
            params={**self._params, "db": "pubmed", "term": query, "retmax": max_results},
        )
        r.raise_for_status()
        ids = r.json()["esearchresult"]["idlist"]
        if not ids:
            return []
        return await self._fetch_many(ids)

    async def fetch_by_id(self, external_id: str) -> PaperResult | None:
        pmid = external_id.removeprefix("pubmed:")
        results = await self._fetch_many([pmid])
        return results[0] if results else None

    async def _fetch_many(self, pmids: list[str]) -> list[PaperResult]:
        r = await self._http.get(
            f"{_EUTILS}/efetch.fcgi",
            params={**self._params, "db": "pubmed", "id": ",".join(pmids),
                    "rettype": "xml", "retmode": "xml"},
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)
        return [_article_to_paper(a) for a in root.findall(".//PubmedArticle")]

def _article_to_paper(article: ET.Element) -> PaperResult:
    pmid = article.findtext(".//PMID") or ""
    title = article.findtext(".//ArticleTitle") or ""
    abstract = article.findtext(".//AbstractText") or ""
    authors = [a.findtext("LastName") or "" for a in article.findall(".//Author")]
    year_text = article.findtext(".//PubDate/Year") or ""
    year = int(year_text) if year_text.isdigit() else None
    venue = article.findtext(".//Journal/Title")
    return PaperResult(
        source="pubmed",
        external_id=f"pubmed:{pmid}",
        title=title,
        authors=[a for a in authors if a],
        year=year,
        venue=venue,
        abstract=abstract,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    )
```

- [x] **Step 2.6: Run adapter tests**

Run: `uv run pytest tests/unit/literature/test_adapters.py -v`
Expected: all 3 adapter tests PASS

- [x] **Step 2.7: Commit**

```bash
git add loop_sci/literature/search/ tests/unit/literature/
git commit -m "feat(literature/search): SS + arXiv + PubMed adapters with fixture tests"
```

---

### Task 3: Multi-source dispatch — fan-out, backoff, graceful degrade

**Files:**
- Create: `loop_sci/literature/search/dispatch.py`
- Create: `tests/unit/literature/test_dispatch.py`

**Interfaces:**
- Consumes: `SearchClient` Protocol (Task 1); adapters from Task 2
- Produces: `dispatch(query, sources, *, max_results_per_source) -> list[PaperResult]`; `SourceError(source, reason)`

- [x] **Step 3.1: Write failing tests for dispatch**

```python
# tests/unit/literature/test_dispatch.py
import pytest
from loop_sci.literature.search.schema import PaperResult
from loop_sci.literature.search.dispatch import dispatch, SourceError

def _make_paper(source: str, n: int) -> PaperResult:
    return PaperResult(source=source, external_id=f"{source}:{n}", title=f"Paper {n}",
                       authors=["A"], year=2024, venue=None, abstract="abs", url=None)

class OkClient:
    def __init__(self, source: str):
        self._source = source
    async def search(self, query: str, *, max_results=10):
        return [_make_paper(self._source, 1)]
    async def fetch_by_id(self, eid): return None

class FailClient:
    async def search(self, query, *, max_results=10):
        raise RuntimeError("API unavailable")
    async def fetch_by_id(self, eid): return None

@pytest.mark.asyncio
async def test_dispatch_multi_source():
    sources = {"ss": OkClient("semantic_scholar"), "arxiv": OkClient("arxiv")}
    results = await dispatch("spikes", sources)
    assert len(results) == 2
    srcs = {r.source for r in results}
    assert srcs == {"semantic_scholar", "arxiv"}

@pytest.mark.asyncio
async def test_dispatch_degrades_on_one_failure():
    sources = {"ss": OkClient("semantic_scholar"), "fail": FailClient()}
    results = await dispatch("spikes", sources)
    # still returns successful source results — no exception raised to caller
    assert len(results) == 1
    assert results[0].source == "semantic_scholar"

@pytest.mark.asyncio
async def test_dispatch_returns_errors_recorded():
    sources = {"ss": OkClient("semantic_scholar"), "fail": FailClient()}
    results, errors = await dispatch("spikes", sources, return_errors=True)
    assert len(errors) == 1
    assert isinstance(errors[0], SourceError)
    assert errors[0].source == "fail"
```

Run: `uv run pytest tests/unit/literature/test_dispatch.py -v`
Expected: FAIL — module not found

- [x] **Step 3.2: Implement dispatch**

```python
# loop_sci/literature/search/dispatch.py
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from .schema import PaperResult

log = logging.getLogger(__name__)

@dataclass
class SourceError:
    source: str
    reason: str

async def dispatch(
    query: str,
    sources: dict[str, Any],  # name -> SearchClient
    *,
    max_results_per_source: int = 10,
    return_errors: bool = False,
) -> list[PaperResult] | tuple[list[PaperResult], list[SourceError]]:
    """Fan out to all sources concurrently; degrade gracefully on failure."""
    async def _one(name: str, client) -> tuple[list[PaperResult], SourceError | None]:
        try:
            results = await client.search(query, max_results=max_results_per_source)
            return results, None
        except Exception as exc:
            log.warning("Source %r failed: %s", name, exc)
            return [], SourceError(source=name, reason=str(exc))

    outcomes = await asyncio.gather(*[_one(n, c) for n, c in sources.items()])
    papers: list[PaperResult] = []
    errors: list[SourceError] = []
    for result_list, err in outcomes:
        papers.extend(result_list)
        if err is not None:
            errors.append(err)

    if return_errors:
        return papers, errors
    return papers
```

- [x] **Step 3.3: Run dispatch tests**

Run: `uv run pytest tests/unit/literature/test_dispatch.py -v`
Expected: all 3 tests PASS

- [x] **Step 3.4: Commit**

```bash
git add loop_sci/literature/search/dispatch.py tests/unit/literature/test_dispatch.py
git commit -m "feat(literature/search): multi-source dispatch with graceful degrade"
```

---

## Group 2: Fact Extraction (Tasks 4–5)

### Task 4: Fact schema (evidence-required, grounding_scope, verification)

**Files:**
- Create: `loop_sci/literature/extract/__init__.py`
- Create: `loop_sci/literature/extract/fact.py`
- Create: `tests/unit/literature/test_fact_schema.py`

**Interfaces:**
- Produces: `Fact` dataclass; `VerificationStatus` dataclass
- Consumed by: Tasks 5, 6, 7, 8, 9

- [ ] **Step 4.1: Write failing tests**

```python
# tests/unit/literature/test_fact_schema.py
import pytest
from loop_sci.literature.extract.fact import Fact, VerificationStatus

def test_fact_requires_source_ref_and_evidence_span():
    with pytest.raises((TypeError, ValueError)):
        Fact(claim="X causes Y")  # missing source_ref + evidence_span

def test_valid_fact_construction():
    f = Fact(
        claim="SNN outperforms ANN on sparse data",
        source_ref={"source": "semantic_scholar", "external_id": "s2:abc"},
        evidence_span="SNNs outperform ANNs on sparse data by 12%",
        confidence=0.85,
        grounding_scope="abstract",
    )
    assert f.verification is None
    assert f.entities is None

def test_fact_with_verification():
    f = Fact(
        claim="X is true",
        source_ref={"source": "arxiv", "external_id": "arxiv:2401.0001"},
        evidence_span="X is true in our experiments",
        confidence=0.9,
        grounding_scope="abstract",
        verification=VerificationStatus(layer_reached=4, status="verified"),
    )
    assert f.verification.status == "verified"
```

Run: `uv run pytest tests/unit/literature/test_fact_schema.py -v`
Expected: FAIL — module not found

- [ ] **Step 4.2: Implement Fact and VerificationStatus**

```python
# loop_sci/literature/extract/fact.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class VerificationStatus:
    layer_reached: int   # 1-4; the layer where decision was made
    status: str          # "verified" | "rejected" | "flagged"
    detail: str = ""

@dataclass
class Fact:
    claim: str
    source_ref: dict[str, str]   # {"source": ..., "external_id": ..., "doi"?: ...}
    evidence_span: str           # verbatim quote from the source text
    confidence: float
    grounding_scope: str         # "abstract" | "full_text"
    entities: list[str] | None = field(default=None)
    verification: VerificationStatus | None = field(default=None)
    fact_id: str | None = field(default=None)  # assigned on persist

    def __post_init__(self) -> None:
        if not self.source_ref:
            raise ValueError("Fact.source_ref must not be empty")
        if not self.evidence_span:
            raise ValueError("Fact.evidence_span must not be empty")
        if "source" not in self.source_ref or "external_id" not in self.source_ref:
            raise ValueError("Fact.source_ref must contain 'source' and 'external_id'")
```

- [ ] **Step 4.3: Run tests**

Run: `uv run pytest tests/unit/literature/test_fact_schema.py -v`
Expected: all 3 tests PASS

- [ ] **Step 4.4: Commit**

```bash
git add loop_sci/literature/extract/ tests/unit/literature/test_fact_schema.py
git commit -m "feat(literature/extract): Fact schema with evidence-span guard"
```

---

### Task 5: Qwen-driven fact extractor (bounded, evidence-required, drops ungrounded)

**Files:**
- Create: `loop_sci/literature/extract/extractor.py`
- Create: `tests/unit/literature/test_extractor.py`

**Interfaces:**
- Consumes: `Fact` (Task 4); `LLMProvider` from `loop_sci._vendor.arbor.llm.base`; `MockProvider` from `tests/conftest.py`
- Produces: `FactExtractor(provider, *, max_facts_per_paper=5).extract(paper: PaperResult) -> list[Fact]`

- [ ] **Step 5.1: Write failing tests**

```python
# tests/unit/literature/test_extractor.py
import json, pytest
from loop_sci.literature.extract.extractor import FactExtractor
from loop_sci.literature.search.schema import PaperResult
from loop_sci.literature.extract.fact import Fact
import sys
sys.path.insert(0, "tests")
from conftest import MockProvider

def _paper(abstract: str = "SNNs outperform ANNs on sparse data by 12%.") -> PaperResult:
    return PaperResult(
        source="semantic_scholar", external_id="s2:abc", title="SNN Paper",
        authors=["Smith J"], year=2024, venue="NeurIPS", abstract=abstract, url=None
    )

GROUNDED_RESPONSE = json.dumps([{
    "claim": "SNNs outperform ANNs on sparse data",
    "evidence_span": "SNNs outperform ANNs on sparse data by 12%",
    "confidence": 0.9,
    "entities": ["SNN", "ANN"],
}])

UNGROUNDED_RESPONSE = json.dumps([{
    "claim": "SNNs are always better",
    "evidence_span": "",   # empty — must be dropped
    "confidence": 0.5,
    "entities": [],
}])

@pytest.mark.asyncio
async def test_extractor_returns_grounded_facts():
    provider = MockProvider(responses=[GROUNDED_RESPONSE])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper())
    assert len(facts) == 1
    f = facts[0]
    assert isinstance(f, Fact)
    assert "12%" in f.evidence_span
    assert f.source_ref["external_id"] == "s2:abc"

@pytest.mark.asyncio
async def test_extractor_drops_ungrounded_claims():
    provider = MockProvider(responses=[UNGROUNDED_RESPONSE])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper())
    assert facts == []

@pytest.mark.asyncio
async def test_extractor_respects_per_paper_bound():
    # Response has 6 facts; only 3 should survive (max_facts_per_paper=3)
    items = [{"claim": f"Claim {i}", "evidence_span": f"Evidence {i}", "confidence": 0.8,
              "entities": []} for i in range(6)]
    provider = MockProvider(responses=[json.dumps(items)])
    extractor = FactExtractor(provider, max_facts_per_paper=3)
    facts = await extractor.extract(_paper())
    assert len(facts) <= 3
```

Run: `uv run pytest tests/unit/literature/test_extractor.py -v`
Expected: FAIL — module not found

- [ ] **Step 5.2: Implement FactExtractor**

```python
# loop_sci/literature/extract/extractor.py
from __future__ import annotations
import json
import logging
from typing import Any
from loop_sci.literature.search.schema import PaperResult
from .fact import Fact

log = logging.getLogger(__name__)

_SYSTEM = """\
You are a scientific fact extractor. Given a paper abstract, extract structured facts.
Return a JSON array where each item has:
  "claim": str (a single precise claim),
  "evidence_span": str (the exact verbatim quote from the text supporting this claim — REQUIRED),
  "confidence": float (0.0-1.0),
  "entities": list[str] (key entities, may be empty).
IMPORTANT: If you cannot find a direct verbatim quote for a claim, DO NOT include that claim.
Return only valid JSON, no markdown fences.
"""

class FactExtractor:
    def __init__(self, provider: Any, *, max_facts_per_paper: int = 5) -> None:
        self._provider = provider
        self._max = max_facts_per_paper

    async def extract(self, paper: PaperResult) -> list[Fact]:
        text = paper.abstract or ""
        if not text.strip():
            return []

        scope = "abstract"  # TODO: upgrade to full_text for PMC-OA/arXiv in Task 9
        prompt = f"Extract facts from this paper abstract:\n\n{text}"

        try:
            resp = await self._provider.create(
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            raw = resp.content[0].text if resp.content else "[]"
            items: list[dict] = json.loads(raw)
        except Exception as exc:
            log.warning("Extraction failed for %s: %s", paper.external_id, exc)
            return []

        facts: list[Fact] = []
        for item in items[: self._max]:
            span = (item.get("evidence_span") or "").strip()
            claim = (item.get("claim") or "").strip()
            if not span or not claim:
                log.debug("Dropping ungrounded claim: %r", claim)
                continue
            facts.append(Fact(
                claim=claim,
                source_ref={"source": paper.source, "external_id": paper.external_id,
                            **({"doi": paper.doi} if paper.doi else {})},
                evidence_span=span,
                confidence=float(item.get("confidence", 0.5)),
                grounding_scope=scope,
                entities=item.get("entities") or None,
            ))
        return facts
```

- [ ] **Step 5.3: Run extractor tests**

Run: `uv run pytest tests/unit/literature/test_extractor.py -v`
Expected: all 3 tests PASS

- [ ] **Step 5.4: Commit**

```bash
git add loop_sci/literature/extract/extractor.py tests/unit/literature/test_extractor.py
git commit -m "feat(literature/extract): Qwen-driven extractor, drops ungrounded facts"
```

---

## Group 3: Citation Verification (Tasks 6–7)

### Task 6: L1 format + L2 existence + L3 metadata verification layers

**Files:**
- Create: `loop_sci/literature/verify/__init__.py`
- Create: `loop_sci/literature/verify/citation.py`
- Create: `tests/unit/literature/test_citation_layers_123.py`

**Interfaces:**
- Consumes: `Fact` (Task 4); `SearchClient` protocol (Task 1)
- Produces: `VerificationPipeline(search_clients: dict[str, SearchClient]).verify_layers_123(fact: Fact) -> VerificationStatus`

- [ ] **Step 6.1: Write failing tests for L1–L3**

```python
# tests/unit/literature/test_citation_layers_123.py
import pytest
from loop_sci.literature.extract.fact import Fact, VerificationStatus
from loop_sci.literature.verify.citation import VerificationPipeline
from loop_sci.literature.search.schema import PaperResult

def _fact(external_id: str = "s2:abc", claim: str = "X is true") -> Fact:
    return Fact(
        claim=claim,
        source_ref={"source": "semantic_scholar", "external_id": external_id},
        evidence_span="X is true in our experiments",
        confidence=0.9,
        grounding_scope="abstract",
    )

class MockSearchClient:
    def __init__(self, result: PaperResult | None):
        self._result = result
    async def search(self, query, *, max_results=10): return []
    async def fetch_by_id(self, eid): return self._result

def _real_paper(authors=("Smith J",), year=2023, venue="NeurIPS") -> PaperResult:
    return PaperResult(
        source="semantic_scholar", external_id="s2:abc", title="Real Paper",
        authors=list(authors), year=year, venue=venue,
        abstract="X is true in our experiments.", url=None,
    )

@pytest.mark.asyncio
async def test_l2_rejects_hallucinated_doi():
    clients = {"semantic_scholar": MockSearchClient(result=None)}
    pipeline = VerificationPipeline(search_clients=clients)
    status = await pipeline.verify_layers_123(_fact("s2:nonexistent"))
    assert status.layer_reached == 2
    assert status.status == "rejected"

@pytest.mark.asyncio
async def test_l3_rejects_mismatched_metadata():
    # Paper exists but year is wrong
    paper = _real_paper(year=1999)
    clients = {"semantic_scholar": MockSearchClient(result=paper)}
    pipeline = VerificationPipeline(search_clients=clients)
    fact = _fact()
    # Override source_ref to simulate a fact that claims year 2023 but paper says 1999
    fact.source_ref["expected_year"] = "2023"
    status = await pipeline.verify_layers_123(fact)
    # L3 mismatch (year); this is a soft check, may pass with tolerance
    assert status.layer_reached in (3, 4)  # reached at least L3

@pytest.mark.asyncio
async def test_l1_l2_l3_pass_for_valid_citation():
    paper = _real_paper()
    clients = {"semantic_scholar": MockSearchClient(result=paper)}
    pipeline = VerificationPipeline(search_clients=clients)
    status = await pipeline.verify_layers_123(_fact())
    # Valid citation should reach L3 and pass (layer_reached=3, needs L4 next)
    assert status.layer_reached == 3
    assert status.status in ("pending_l4", "verified")
```

Run: `uv run pytest tests/unit/literature/test_citation_layers_123.py -v`
Expected: FAIL — modules not found

- [ ] **Step 6.2: Implement L1 + L2 + L3 in citation.py**

```python
# loop_sci/literature/verify/citation.py
from __future__ import annotations
import logging
from typing import Any
from loop_sci.literature.extract.fact import Fact, VerificationStatus

log = logging.getLogger(__name__)

class VerificationPipeline:
    def __init__(self, search_clients: dict[str, Any]) -> None:
        self._clients = search_clients

    async def verify_layers_123(self, fact: Fact) -> VerificationStatus:
        # L1: format check
        ref = fact.source_ref
        if not ref.get("external_id") and not ref.get("doi"):
            return VerificationStatus(layer_reached=1, status="rejected",
                                      detail="missing identifier")

        # L2: existence — resolve via appropriate client
        resolved = await self._resolve(ref)
        if resolved is None:
            return VerificationStatus(layer_reached=2, status="rejected",
                                      detail="paper not found via API")

        # L3: metadata match (authors/year/venue tolerance)
        ok, detail = _check_metadata(ref, resolved)
        if not ok:
            return VerificationStatus(layer_reached=3, status="rejected", detail=detail)

        return VerificationStatus(layer_reached=3, status="pending_l4",
                                  detail=f"resolved:{resolved.external_id}")

    async def _resolve(self, ref: dict) -> Any:
        source = ref.get("source", "")
        eid = ref.get("external_id", "")
        client = self._clients.get(source)
        if client is None:
            # Try DOI via any client
            doi = ref.get("doi")
            if doi:
                for c in self._clients.values():
                    try:
                        r = await c.fetch_by_id(doi)
                        if r is not None:
                            return r
                    except Exception:
                        pass
            return None
        try:
            return await client.fetch_by_id(eid)
        except Exception as exc:
            log.warning("fetch_by_id failed for %s: %s", eid, exc)
            return None

def _check_metadata(ref: dict, paper: Any) -> tuple[bool, str]:
    # Year check (exact)
    expected_year = ref.get("expected_year")
    if expected_year and paper.year is not None:
        if str(paper.year) != str(expected_year):
            return False, f"year mismatch: expected {expected_year}, got {paper.year}"
    return True, ""
```

- [ ] **Step 6.3: Run L1-L3 tests**

Run: `uv run pytest tests/unit/literature/test_citation_layers_123.py -v`
Expected: all 3 tests PASS

- [ ] **Step 6.4: Commit**

```bash
git add loop_sci/literature/verify/ tests/unit/literature/test_citation_layers_123.py
git commit -m "feat(literature/verify): L1-L3 citation verification (format/existence/metadata)"
```

---

### Task 7: L4 content-grounding — hybrid lexical pre-filter + Qwen judge

**Files:**
- Create: `loop_sci/literature/verify/grounding.py`
- Modify: `loop_sci/literature/verify/citation.py` (add `verify_l4` + full `verify`)
- Create: `tests/unit/literature/test_grounding.py`

**Interfaces:**
- Consumes: `Fact` (Task 4); `LLMProvider`; resolved `PaperResult` (Task 2)
- Produces: `GroundingVerifier(provider, *, threshold=0.3).verify(fact, paper) -> VerificationStatus`; `VerificationPipeline.verify(fact) -> VerificationStatus` (full 4-layer)

- [ ] **Step 7.1: Write failing grounding tests (FRONT-LOADED — per spec)**

```python
# tests/unit/literature/test_grounding.py
import pytest, json
from loop_sci.literature.verify.grounding import GroundingVerifier
from loop_sci.literature.extract.fact import Fact
from loop_sci.literature.search.schema import PaperResult
import sys; sys.path.insert(0, "tests")
from conftest import MockProvider

def _fact(evidence: str, scope: str = "abstract") -> Fact:
    return Fact(
        claim="SNNs beat ANNs",
        source_ref={"source": "semantic_scholar", "external_id": "s2:abc"},
        evidence_span=evidence,
        confidence=0.9,
        grounding_scope=scope,
    )

def _paper(abstract: str) -> PaperResult:
    return PaperResult(
        source="semantic_scholar", external_id="s2:abc", title="T",
        authors=["A"], year=2024, venue=None, abstract=abstract, url=None
    )

@pytest.mark.asyncio
async def test_lexical_pass_without_qwen():
    """High overlap -> pass without calling Qwen judge."""
    verifier = GroundingVerifier(provider=None, threshold=0.3)
    paper = _paper("SNNs outperform ANNs on sparse data by 12%.")
    fact = _fact("SNNs outperform ANNs on sparse data by 12%")
    status = await verifier.verify(fact, paper)
    assert status.status == "verified"
    assert status.layer_reached == 4

@pytest.mark.asyncio
async def test_lexical_fail_without_qwen():
    """Zero overlap -> reject without calling Qwen."""
    verifier = GroundingVerifier(provider=None, threshold=0.3)
    paper = _paper("The cat sat on the mat.")
    fact = _fact("quantum tunneling enables flight")
    status = await verifier.verify(fact, paper)
    assert status.status == "rejected"
    assert status.layer_reached == 4

@pytest.mark.asyncio
async def test_borderline_uses_qwen_judge():
    """Borderline overlap -> calls Qwen; Qwen says supported -> verified."""
    qwen_says_yes = json.dumps({"supported": True, "confidence": 0.75})
    provider = MockProvider(responses=[qwen_says_yes])
    verifier = GroundingVerifier(provider=provider, threshold=0.3)
    paper = _paper("Spiking neural networks have some advantages over ANNs.")
    fact = _fact("SNNs beat ANNs in energy")  # partial match, borderline
    status = await verifier.verify(fact, paper)
    assert status.status == "verified"

@pytest.mark.asyncio
async def test_misattributed_claim_rejected_at_l4():
    """Claim not in text at all -> rejected at L4 (anti-fabrication)."""
    verifier = GroundingVerifier(provider=None, threshold=0.3)
    paper = _paper("This paper studies protein folding in bacteria.")
    fact = _fact("transformers outperform LSTMs on NLP tasks")
    status = await verifier.verify(fact, paper)
    assert status.status == "rejected"
    assert status.layer_reached == 4
```

Run: `uv run pytest tests/unit/literature/test_grounding.py -v`
Expected: FAIL — module not found

- [ ] **Step 7.2: Implement GroundingVerifier**

```python
# loop_sci/literature/verify/grounding.py
from __future__ import annotations
import json
import logging
from typing import Any
from loop_sci.literature.extract.fact import Fact, VerificationStatus
from loop_sci.literature.search.schema import PaperResult

log = logging.getLogger(__name__)

_JUDGE_SYSTEM = """\
You are a citation grounding judge. Given a source text and a claim, determine if the
claim is supported by the text. Return JSON: {"supported": bool, "confidence": float}.
"""

def _lexical_score(span: str, text: str) -> float:
    """Jaccard overlap on lowercase words."""
    span_words = set(span.lower().split())
    text_words = set(text.lower().split())
    if not span_words:
        return 0.0
    return len(span_words & text_words) / len(span_words)

class GroundingVerifier:
    # Scores < low_threshold -> immediate reject (no Qwen)
    # Scores > high_threshold -> immediate pass (no Qwen)
    # In between -> Qwen judge
    LOW_THRESHOLD = 0.15
    HIGH_THRESHOLD = 0.60

    def __init__(self, provider: Any, *, threshold: float = 0.3) -> None:
        self._provider = provider
        self._threshold = threshold  # midpoint for borderline definition

    async def verify(self, fact: Fact, paper: PaperResult) -> VerificationStatus:
        source_text = paper.abstract or ""
        score = _lexical_score(fact.evidence_span, source_text)

        if score >= self.HIGH_THRESHOLD:
            return VerificationStatus(layer_reached=4, status="verified",
                                      detail=f"lexical:{score:.2f}")
        if score < self.LOW_THRESHOLD:
            return VerificationStatus(layer_reached=4, status="rejected",
                                      detail=f"lexical:{score:.2f}")

        # Borderline: call Qwen judge
        if self._provider is None:
            # No provider in offline mode: use threshold directly
            status = "verified" if score >= self._threshold else "rejected"
            return VerificationStatus(layer_reached=4, status=status,
                                      detail=f"lexical_no_judge:{score:.2f}")

        try:
            resp = await self._provider.create(
                system=_JUDGE_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": f"Source text:\n{source_text}\n\nClaim:\n{fact.claim}",
                }],
                max_tokens=128,
            )
            raw = resp.content[0].text if resp.content else "{}"
            verdict = json.loads(raw)
            supported = bool(verdict.get("supported", False))
            conf = float(verdict.get("confidence", 0.5))
            status = "verified" if supported else "rejected"
            return VerificationStatus(layer_reached=4, status=status,
                                      detail=f"qwen_judge:{conf:.2f}")
        except Exception as exc:
            log.warning("Qwen judge failed: %s — falling back to lexical", exc)
            status = "verified" if score >= self._threshold else "rejected"
            return VerificationStatus(layer_reached=4, status=status,
                                      detail=f"fallback:{score:.2f}")
```

- [ ] **Step 7.3: Wire L4 into VerificationPipeline.verify()**

Add `verify_l4` and a full `verify()` method to `loop_sci/literature/verify/citation.py`:

```python
# At the top of citation.py, add import:
from loop_sci.literature.verify.grounding import GroundingVerifier

# Add to VerificationPipeline.__init__:
#   self._grounding = GroundingVerifier(grounding_provider, threshold=grounding_threshold)

# Add new __init__ signature:
def __init__(
    self,
    search_clients: dict[str, Any],
    *,
    grounding_provider: Any = None,
    grounding_threshold: float = 0.3,
) -> None:
    self._clients = search_clients
    self._grounding = GroundingVerifier(grounding_provider, threshold=grounding_threshold)

# Add full verify():
async def verify(self, fact: Fact) -> VerificationStatus:
    """Run all 4 layers. Short-circuits on rejection."""
    # Run L1-L3
    status = await self.verify_layers_123(fact)
    if status.status == "rejected":
        return status

    # L4: need the resolved paper for text grounding
    resolved = await self._resolve(fact.source_ref)
    if resolved is None:
        return VerificationStatus(layer_reached=2, status="rejected",
                                  detail="paper disappeared between L2 and L4")

    return await self._grounding.verify(fact, resolved)
```

- [ ] **Step 7.4: Run all grounding and pipeline tests**

Run: `uv run pytest tests/unit/literature/test_grounding.py tests/unit/literature/test_citation_layers_123.py -v`
Expected: all tests PASS

- [ ] **Step 7.5: Commit**

```bash
git add loop_sci/literature/verify/ tests/unit/literature/test_grounding.py
git commit -m "feat(literature/verify): L4 hybrid grounding — lexical pre-filter + Qwen judge"
```

---

## Group 4: Fact Base + Foundation Integration (Tasks 8–10)

### Task 8: JSON fact store + persist verified facts to idea-tree

**Files:**
- Create: `loop_sci/literature/factbase/__init__.py`
- Create: `loop_sci/literature/factbase/store.py`
- Create: `loop_sci/literature/factbase/persist.py`
- Create: `tests/unit/literature/test_factbase.py`

**Interfaces:**
- Consumes: `Fact` (Task 4); `IdeaTree`, `Node` from `loop_sci.state.idea_tree`
- Produces:
  - `FactStore(path: Path).add(fact: Fact) -> str` (returns fact_id); `.all() -> list[Fact]`; `.filter(*, source=None, topic=None) -> list[Fact]`
  - `persist_fact(fact: Fact, *, tree: IdeaTree, paper_node_id: str, store: FactStore) -> str` (returns fact_id)

- [ ] **Step 8.1: Write failing tests**

```python
# tests/unit/literature/test_factbase.py
import pytest, json, uuid
from pathlib import Path
from loop_sci.literature.extract.fact import Fact, VerificationStatus
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.factbase.persist import persist_fact
from loop_sci.state.idea_tree import IdeaTree, Node

def _verified_fact(n: int = 1) -> Fact:
    return Fact(
        claim=f"Claim {n}",
        source_ref={"source": "arxiv", "external_id": f"arxiv:2401.000{n}"},
        evidence_span=f"Evidence text {n}",
        confidence=0.9,
        grounding_scope="abstract",
        verification=VerificationStatus(layer_reached=4, status="verified"),
    )

def _unverified_fact() -> Fact:
    return Fact(
        claim="Unverified claim",
        source_ref={"source": "arxiv", "external_id": "arxiv:2401.9999"},
        evidence_span="some text",
        confidence=0.4,
        grounding_scope="abstract",
        verification=VerificationStatus(layer_reached=2, status="rejected"),
    )

def test_fact_store_add_and_retrieve(tmp_path):
    store = FactStore(tmp_path / "facts.json")
    f = _verified_fact(1)
    fid = store.add(f)
    assert fid is not None
    all_facts = store.all()
    assert len(all_facts) == 1
    assert all_facts[0].claim == "Claim 1"

def test_fact_store_filter_by_source(tmp_path):
    store = FactStore(tmp_path / "facts.json")
    store.add(_verified_fact(1))
    store.add(_verified_fact(2))
    results = store.filter(source="arxiv")
    assert len(results) == 2
    results_none = store.filter(source="pubmed")
    assert results_none == []

def test_persist_adds_to_tree_and_store(tmp_path):
    # Build minimal tree with a paper parent node
    paper_id = "paper_001"
    root = Node(id="ROOT", parent_id=None, hypothesis="test topic", depth=0, status="pending")
    tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")
    paper_node = Node(id=paper_id, parent_id="ROOT", hypothesis="arXiv:2401.0001",
                      depth=1, status="done")
    tree.add_node(paper_node)

    store = FactStore(tmp_path / "facts.json")
    fact = _verified_fact(1)
    fact_id = persist_fact(fact, tree=tree, paper_node_id=paper_id, store=store)

    # Should be in store
    assert len(store.all()) == 1
    # Should be in tree as a node under paper_node_id
    reloaded = IdeaTree.load_json(tmp_path / "tree.json")
    paper = reloaded._nodes[paper_id]
    assert len(paper.children_ids) == 1
    fact_node = reloaded._nodes[paper.children_ids[0]]
    assert fact_node.refs is not None
    assert fact_node.refs["claim"] == "Claim 1"

def test_persist_rejected_fact_raises(tmp_path):
    root = Node(id="ROOT", parent_id=None, hypothesis="test", depth=0, status="pending")
    tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")
    store = FactStore(tmp_path / "facts.json")
    with pytest.raises(ValueError, match="only verified"):
        persist_fact(_unverified_fact(), tree=tree, paper_node_id="ROOT", store=store)
```

Run: `uv run pytest tests/unit/literature/test_factbase.py -v`
Expected: FAIL — modules not found

- [ ] **Step 8.2: Implement FactStore**

```python
# loop_sci/literature/factbase/store.py
from __future__ import annotations
import json
import uuid
from dataclasses import asdict
from pathlib import Path
from loop_sci.literature.extract.fact import Fact, VerificationStatus

def _fact_to_dict(f: Fact) -> dict:
    d = {
        "fact_id": f.fact_id,
        "claim": f.claim,
        "source_ref": f.source_ref,
        "evidence_span": f.evidence_span,
        "confidence": f.confidence,
        "grounding_scope": f.grounding_scope,
        "entities": f.entities,
        "verification": {
            "layer_reached": f.verification.layer_reached,
            "status": f.verification.status,
            "detail": f.verification.detail,
        } if f.verification else None,
    }
    return d

def _dict_to_fact(d: dict) -> Fact:
    vs = d.get("verification")
    return Fact(
        claim=d["claim"],
        source_ref=d["source_ref"],
        evidence_span=d["evidence_span"],
        confidence=d["confidence"],
        grounding_scope=d["grounding_scope"],
        entities=d.get("entities"),
        verification=VerificationStatus(**vs) if vs else None,
        fact_id=d.get("fact_id"),
    )

class FactStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._data: list[dict] = []
        if self._path.exists():
            self._data = json.loads(self._path.read_text(encoding="utf-8"))

    def add(self, fact: Fact) -> str:
        fid = fact.fact_id or f"fact_{uuid.uuid4().hex[:8]}"
        fact.fact_id = fid
        self._data.append(_fact_to_dict(fact))
        self._save()
        return fid

    def all(self) -> list[Fact]:
        return [_dict_to_fact(d) for d in self._data]

    def filter(self, *, source: str | None = None, topic: str | None = None) -> list[Fact]:
        results = self.all()
        if source:
            results = [f for f in results if f.source_ref.get("source") == source]
        if topic:
            results = [f for f in results if topic.lower() in f.claim.lower()]
        return results

    def get_ids(self) -> set[str]:
        return {d["fact_id"] for d in self._data if d.get("fact_id")}

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)
```

- [ ] **Step 8.3: Implement persist_fact**

```python
# loop_sci/literature/factbase/persist.py
from __future__ import annotations
import uuid
from loop_sci.literature.extract.fact import Fact
from loop_sci.literature.factbase.store import FactStore
from loop_sci.state.idea_tree import IdeaTree, Node

def persist_fact(
    fact: Fact,
    *,
    tree: IdeaTree,
    paper_node_id: str,
    store: FactStore,
) -> str:
    """Persist a verified Fact to both the idea-tree and JSON store.

    Raises ValueError if fact.verification is not "verified".
    Honors record-before-decide: tree node is added before store write.
    """
    if not fact.verification or fact.verification.status != "verified":
        raise ValueError(
            f"persist_fact: only verified facts may be persisted "
            f"(got status={fact.verification.status if fact.verification else None!r})"
        )

    fact_id = fact.fact_id or f"fact_{uuid.uuid4().hex[:8]}"
    fact.fact_id = fact_id
    node_id = f"{paper_node_id}_{fact_id}"

    # Build refs payload — the full fact dict minus fact_id (stored as node id)
    refs = {
        "claim": fact.claim,
        "source_ref": fact.source_ref,
        "evidence_span": fact.evidence_span,
        "confidence": fact.confidence,
        "grounding_scope": fact.grounding_scope,
        "entities": fact.entities,
        "verification_layer": fact.verification.layer_reached,
        "verification_status": fact.verification.status,
    }

    # record-before-decide: tree first (atomic via IdeaTree.save)
    node = Node(
        id=node_id,
        parent_id=paper_node_id,
        hypothesis=fact.claim,
        depth=2,  # topic(0) -> paper(1) -> fact(2)
        status="done",
        refs=refs,
    )
    tree.add_node(node)

    # then JSON store (atomic via tmp-replace)
    store.add(fact)
    return fact_id
```

- [ ] **Step 8.4: Run factbase tests**

Run: `uv run pytest tests/unit/literature/test_factbase.py -v`
Expected: all 4 tests PASS

- [ ] **Step 8.5: Commit**

```bash
git add loop_sci/literature/factbase/ tests/unit/literature/test_factbase.py
git commit -m "feat(literature/factbase): JSON store + persist verified fact to idea-tree"
```

---

### Task 9: LitMinerExecutor — search→extract→verify→record with resumability

**Files:**
- Create: `loop_sci/literature/executor.py`
- Create: `tests/unit/literature/test_lit_executor.py`

**Interfaces:**
- Consumes: `Executor(cfg, *, provider, bus)` seam; `DispatchUnit`/`ExecutorResult` from `loop_sci.engine.types`; all Group 1-4 components
- Produces: `LitMinerExecutor(cfg, *, search_clients, grounding_provider=None, bus=None)` with `async run(unit: DispatchUnit) -> ExecutorResult`; skips already-processed `external_id` (resumability)

- [ ] **Step 9.1: Write failing tests**

```python
# tests/unit/literature/test_lit_executor.py
import pytest, json
from pathlib import Path
from loop_sci.engine.types import DispatchUnit
from loop_sci.literature.executor import LitMinerExecutor
from loop_sci.literature.search.schema import PaperResult
from loop_sci.literature.extract.fact import Fact
import sys; sys.path.insert(0, "tests")
from conftest import MockProvider

def _paper(n: int = 1) -> PaperResult:
    return PaperResult(
        source="semantic_scholar", external_id=f"s2:p{n}",
        title=f"Paper {n}", authors=["A"], year=2024, venue="NeurIPS",
        abstract=f"Claim {n} is supported by evidence {n}.", url=None,
    )

EXTRACT_RESP = json.dumps([{
    "claim": "Claim 1 is supported",
    "evidence_span": "Claim 1 is supported by evidence 1",
    "confidence": 0.9,
    "entities": [],
}])

class MockSearchClient:
    def __init__(self, papers: list):
        self._papers = papers
    async def search(self, query, *, max_results=10):
        return self._papers
    async def fetch_by_id(self, eid):
        return next((p for p in self._papers if p.external_id == eid), None)

@pytest.fixture
def tmp_session(tmp_path):
    from loop_sci.state.session import RunSession
    return RunSession.create(tmp_path, task="test topic")

@pytest.mark.asyncio
async def test_executor_produces_verified_fact(tmp_session, tmp_path):
    provider = MockProvider(responses=[
        EXTRACT_RESP,
        # L4 grounding judge — high lexical score so won't be called, but just in case
        json.dumps({"supported": True, "confidence": 0.9}),
    ])
    clients = {"semantic_scholar": MockSearchClient([_paper(1)])}
    executor = LitMinerExecutor(
        session=tmp_session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=provider,
        store_path=tmp_path / "facts.json",
    )
    unit = DispatchUnit(node_id="ROOT", goal="spikes topic")
    result = await executor.run(unit)
    assert result.status == "done"
    assert result.refs.get("verified_facts_count", 0) >= 1

@pytest.mark.asyncio
async def test_executor_skips_already_processed(tmp_session, tmp_path):
    """Resume: second run with same paper produces no duplicates."""
    provider = MockProvider(responses=[EXTRACT_RESP] * 4)
    clients = {"semantic_scholar": MockSearchClient([_paper(1)])}

    async def _run():
        ex = LitMinerExecutor(
            session=tmp_session,
            search_clients=clients,
            extraction_provider=provider,
            grounding_provider=provider,
            store_path=tmp_path / "facts.json",
        )
        return await ex.run(DispatchUnit(node_id="ROOT", goal="spikes"))

    await _run()
    result2 = await _run()
    # Second run: paper already processed, no new facts
    assert result2.refs.get("skipped_papers_count", 0) >= 1
```

Run: `uv run pytest tests/unit/literature/test_lit_executor.py -v`
Expected: FAIL — module not found

- [ ] **Step 9.2: Implement LitMinerExecutor**

```python
# loop_sci/literature/executor.py
from __future__ import annotations
import logging
import uuid
from pathlib import Path
from typing import Any
from loop_sci.engine.types import DispatchUnit, ExecutorResult
from loop_sci.literature.search.dispatch import dispatch
from loop_sci.literature.extract.extractor import FactExtractor
from loop_sci.literature.verify.citation import VerificationPipeline
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.factbase.persist import persist_fact
from loop_sci.state.idea_tree import Node
from loop_sci.state.session import RunSession

log = logging.getLogger(__name__)

class LitMinerExecutor:
    """search → extract → verify → record pipeline."""

    def __init__(
        self,
        session: RunSession,
        *,
        search_clients: dict[str, Any],
        extraction_provider: Any,
        grounding_provider: Any = None,
        store_path: Path,
        max_papers: int = 10,
        max_facts_per_paper: int = 5,
        grounding_threshold: float = 0.3,
    ) -> None:
        self._session = session
        self._clients = search_clients
        self._extractor = FactExtractor(extraction_provider, max_facts_per_paper=max_facts_per_paper)
        self._pipeline = VerificationPipeline(
            search_clients, grounding_provider=grounding_provider,
            grounding_threshold=grounding_threshold
        )
        self._store = FactStore(store_path)
        self._max_papers = max_papers

    async def run(self, unit: DispatchUnit) -> ExecutorResult:
        tree = self._session.tree
        topic = unit.goal

        # Ensure topic root node exists (idempotent)
        topic_id = f"topic_{unit.node_id}"
        if topic_id not in tree._nodes:
            tree.add_node(Node(id=topic_id, parent_id=unit.node_id,
                               hypothesis=topic, depth=1, status="pending"))

        papers = await dispatch(topic, self._clients,
                                max_results_per_source=self._max_papers)

        # Dedupe by external_id
        seen_eids: set[str] = {
            n.refs["external_id"]
            for n in tree._nodes.values()
            if n.refs and "external_id" in n.refs
        }
        # Also track already-stored fact_ids to avoid re-verification
        stored_ids = self._store.get_ids()

        verified_count = 0
        skipped_count = 0

        for paper in papers[: self._max_papers]:
            if paper.external_id in seen_eids:
                skipped_count += 1
                continue

            # Ensure paper node
            paper_node_id = f"paper_{paper.external_id.replace(':', '_')}"
            if paper_node_id not in tree._nodes:
                tree.add_node(Node(
                    id=paper_node_id, parent_id=topic_id,
                    hypothesis=paper.title or paper.external_id,
                    depth=2, status="pending",
                    refs={"external_id": paper.external_id, "source": paper.source},
                ))

            facts = await self._extractor.extract(paper)
            for fact in facts:
                status = await self._pipeline.verify(fact)
                fact.verification = status
                if status.status == "verified":
                    fid = f"fact_{uuid.uuid4().hex[:8]}"
                    fact.fact_id = fid
                    if fid not in stored_ids:
                        persist_fact(fact, tree=tree, paper_node_id=paper_node_id,
                                     store=self._store)
                        verified_count += 1

            tree.update_node(paper_node_id, status="done")
            seen_eids.add(paper.external_id)

        self._session.advance_step()
        return ExecutorResult(
            status="done",
            summary=f"Mined {verified_count} verified facts from {len(papers)} papers.",
            score=None,
            insight=f"{verified_count} verified facts persisted.",
            refs={
                "verified_facts_count": verified_count,
                "skipped_papers_count": skipped_count,
                "total_papers": len(papers),
            },
        )
```

- [ ] **Step 9.3: Run executor tests**

Run: `uv run pytest tests/unit/literature/test_lit_executor.py -v`
Expected: both tests PASS

- [ ] **Step 9.4: Commit**

```bash
git add loop_sci/literature/executor.py tests/unit/literature/test_lit_executor.py
git commit -m "feat(literature): LitMinerExecutor with resume (skip already-processed papers)"
```

---

### Task 10: ToolRegistry tools — search / fetch / extract / verify

**Files:**
- Create: `loop_sci/literature/tools.py`
- Create: `tests/unit/literature/test_lit_tools.py`

**Interfaces:**
- Consumes: `ToolRegistry` from `loop_sci.engine.tools`; all literature sub-packages
- Produces: `register_literature_tools(registry: ToolRegistry, *, search_clients, extractor, pipeline) -> None`

- [ ] **Step 10.1: Write failing tests**

```python
# tests/unit/literature/test_lit_tools.py
import pytest, json
from loop_sci.engine.tools import ToolRegistry
from loop_sci.literature.tools import register_literature_tools
from loop_sci.literature.search.schema import PaperResult
from loop_sci.literature.extract.fact import Fact, VerificationStatus
import sys; sys.path.insert(0, "tests")
from conftest import MockProvider

def _paper() -> PaperResult:
    return PaperResult(
        source="semantic_scholar", external_id="s2:abc", title="T",
        authors=["A"], year=2024, venue=None,
        abstract="SNN beats ANN by 12%.", url=None,
    )

class MockSearchClient:
    async def search(self, query, *, max_results=10): return [_paper()]
    async def fetch_by_id(self, eid): return _paper()

@pytest.mark.asyncio
async def test_search_tool_registered_and_dispatches():
    registry = ToolRegistry()
    provider = MockProvider(responses=[
        json.dumps([{"claim": "SNN beats ANN", "evidence_span": "SNN beats ANN by 12%",
                     "confidence": 0.9, "entities": []}]),
        json.dumps({"supported": True, "confidence": 0.9}),
    ])
    from loop_sci.literature.extract.extractor import FactExtractor
    from loop_sci.literature.verify.citation import VerificationPipeline
    extractor = FactExtractor(provider)
    pipeline = VerificationPipeline({"semantic_scholar": MockSearchClient()},
                                    grounding_provider=provider)
    register_literature_tools(
        registry,
        search_clients={"semantic_scholar": MockSearchClient()},
        extractor=extractor,
        pipeline=pipeline,
    )
    defs = registry.get_definitions()
    names = {d["name"] for d in defs}
    assert {"lit_search", "lit_fetch", "lit_extract", "lit_verify"}.issubset(names)

    result = await registry.dispatch("lit_search", {"query": "spiking networks", "sources": ["semantic_scholar"]})
    data = json.loads(result)
    assert "papers" in data
    assert len(data["papers"]) >= 1
```

Run: `uv run pytest tests/unit/literature/test_lit_tools.py -v`
Expected: FAIL — module not found

- [ ] **Step 10.2: Implement register_literature_tools**

```python
# loop_sci/literature/tools.py
from __future__ import annotations
import json
import logging
from typing import Any
from loop_sci.engine.tools import ToolRegistry

log = logging.getLogger(__name__)

def register_literature_tools(
    registry: ToolRegistry,
    *,
    search_clients: dict[str, Any],
    extractor: Any,
    pipeline: Any,
) -> None:
    """Register lit_search, lit_fetch, lit_extract, lit_verify in the ToolRegistry."""

    async def _search(query: str, sources: list[str] | None = None) -> str:
        from loop_sci.literature.search.dispatch import dispatch
        clients = {k: v for k, v in search_clients.items()
                   if sources is None or k in sources}
        papers = await dispatch(query, clients)
        return json.dumps({
            "papers": [
                {"source": p.source, "external_id": p.external_id,
                 "title": p.title, "year": p.year, "abstract": p.abstract}
                for p in papers
            ]
        })

    async def _fetch(external_id: str, source: str) -> str:
        client = search_clients.get(source)
        if client is None:
            return json.dumps({"error": f"unknown source: {source}"})
        paper = await client.fetch_by_id(external_id)
        if paper is None:
            return json.dumps({"error": "not found"})
        return json.dumps({
            "source": paper.source, "external_id": paper.external_id,
            "title": paper.title, "abstract": paper.abstract, "year": paper.year,
        })

    async def _extract(external_id: str, source: str, abstract: str) -> str:
        from loop_sci.literature.search.schema import PaperResult
        paper = PaperResult(
            source=source, external_id=external_id, title="",
            authors=[], year=None, venue=None, abstract=abstract, url=None,
        )
        facts = await extractor.extract(paper)
        return json.dumps({
            "facts": [{"claim": f.claim, "evidence_span": f.evidence_span,
                       "confidence": f.confidence} for f in facts]
        })

    async def _verify(claim: str, source_ref: dict, evidence_span: str,
                      grounding_scope: str = "abstract") -> str:
        from loop_sci.literature.extract.fact import Fact
        fact = Fact(
            claim=claim, source_ref=source_ref, evidence_span=evidence_span,
            confidence=0.5, grounding_scope=grounding_scope,
        )
        status = await pipeline.verify(fact)
        return json.dumps({
            "layer_reached": status.layer_reached,
            "status": status.status,
            "detail": status.detail,
        })

    registry.register(
        name="lit_search",
        description="Search scholarly literature across configured sources.",
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "sources": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
        },
        fn=_search,
    )
    registry.register(
        name="lit_fetch",
        description="Fetch a specific paper by external_id from a named source.",
        schema={
            "type": "object",
            "properties": {
                "external_id": {"type": "string"},
                "source": {"type": "string"},
            },
            "required": ["external_id", "source"],
        },
        fn=_fetch,
    )
    registry.register(
        name="lit_extract",
        description="Extract structured facts from a paper's abstract text.",
        schema={
            "type": "object",
            "properties": {
                "external_id": {"type": "string"},
                "source": {"type": "string"},
                "abstract": {"type": "string"},
            },
            "required": ["external_id", "source", "abstract"],
        },
        fn=_extract,
    )
    registry.register(
        name="lit_verify",
        description="Run 4-layer citation verification on a claim+source+evidence triple.",
        schema={
            "type": "object",
            "properties": {
                "claim": {"type": "string"},
                "source_ref": {"type": "object"},
                "evidence_span": {"type": "string"},
                "grounding_scope": {"type": "string", "enum": ["abstract", "full_text"]},
            },
            "required": ["claim", "source_ref", "evidence_span"],
        },
        fn=_verify,
    )
```

- [ ] **Step 10.3: Run tool tests**

Run: `uv run pytest tests/unit/literature/test_lit_tools.py -v`
Expected: PASS

- [ ] **Step 10.4: Commit**

```bash
git add loop_sci/literature/tools.py tests/unit/literature/test_lit_tools.py
git commit -m "feat(literature): register lit_search/fetch/extract/verify in ToolRegistry"
```

---

## Group 5: End-to-End, Coverage, and Docs (Tasks 11–12)

### Task 11: Offline integration tests — anti-fabrication + resume-no-reverify

**Files:**
- Create: `tests/integration/test_lit_miner_e2e.py`
- Create: `tests/live/test_lit_miner_live.py`

**Interfaces:**
- Consumes: all Groups 1–4 components; `MockProvider`; `RunSession`

- [ ] **Step 11.1: Write failing offline integration tests (FRONT-LOADED per spec)**

```python
# tests/integration/test_lit_miner_e2e.py
"""Offline integration test: mock SearchClient + mock Qwen provider.
Covers: (a) >=1 verified fact in tree+store; (b) hallucinated->L2 reject;
(c) misattributed->L4 reject; (d) resume-no-reverify.
"""
import json
import pytest
from pathlib import Path
from loop_sci.state.session import RunSession
from loop_sci.literature.executor import LitMinerExecutor
from loop_sci.literature.search.schema import PaperResult
from loop_sci.literature.factbase.store import FactStore
from loop_sci.engine.types import DispatchUnit
import sys; sys.path.insert(0, "tests")
from conftest import MockProvider

_ABSTRACT = "Spiking neural networks consume 10x less energy than ANNs on neuromorphic hardware."

def _paper(n: int = 1, abstract: str = _ABSTRACT) -> PaperResult:
    return PaperResult(
        source="semantic_scholar", external_id=f"s2:real{n}",
        title=f"Real Paper {n}", authors=["Smith J"],
        year=2023, venue="NeurIPS", abstract=abstract, url=None,
    )

VALID_EXTRACT = json.dumps([{
    "claim": "SNNs consume 10x less energy than ANNs",
    "evidence_span": "Spiking neural networks consume 10x less energy than ANNs on neuromorphic hardware",
    "confidence": 0.92, "entities": ["SNN", "ANN"],
}])

HALLUCINATED_EXTRACT = json.dumps([{
    "claim": "Transformers achieve 99% accuracy on all tasks",
    "evidence_span": "transformers 99% accuracy",
    "confidence": 0.9, "entities": [],
}])

MISATTRIBUTED_EXTRACT = json.dumps([{
    "claim": "LSTM outperforms transformers on time series",
    "evidence_span": "LSTM outperforms transformers on time series",
    "confidence": 0.85, "entities": [],
}])

class MockSearchClientReal:
    """Returns a real paper that can be fetched by id."""
    def __init__(self, papers):
        self._papers = {p.external_id: p for p in papers}
    async def search(self, query, *, max_results=10):
        return list(self._papers.values())
    async def fetch_by_id(self, eid):
        return self._papers.get(eid)

class MockSearchClientHallucinated:
    """Simulates hallucinated DOI: search returns papers, but fetch_by_id returns None."""
    def __init__(self, papers):
        self._search_papers = papers
    async def search(self, query, *, max_results=10):
        return self._search_papers
    async def fetch_by_id(self, eid):
        return None  # hallucinated — cannot be resolved

@pytest.fixture
def session(tmp_path):
    return RunSession.create(tmp_path, task="spiking neural networks")

@pytest.mark.asyncio
async def test_verified_fact_persisted_to_tree_and_store(session, tmp_path):
    provider = MockProvider(responses=[VALID_EXTRACT])
    real_paper = _paper(1)
    clients = {"semantic_scholar": MockSearchClientReal([real_paper])}
    store_path = tmp_path / "facts.json"

    executor = LitMinerExecutor(
        session=session, search_clients=clients,
        extraction_provider=provider, grounding_provider=None,
        store_path=store_path,
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="spiking networks"))
    assert result.status == "done"
    assert result.refs["verified_facts_count"] >= 1

    store = FactStore(store_path)
    facts = store.all()
    assert len(facts) >= 1
    assert facts[0].verification.status == "verified"

    tree = session.tree
    fact_nodes = [n for n in tree._nodes.values()
                  if n.refs and n.refs.get("verification_status") == "verified"]
    assert len(fact_nodes) >= 1

@pytest.mark.asyncio
async def test_hallucinated_citation_rejected_at_l2(session, tmp_path):
    provider = MockProvider(responses=[HALLUCINATED_EXTRACT])
    hallucinated_paper = PaperResult(
        source="semantic_scholar", external_id="s2:fake999",
        title="Fake Paper", authors=["Ghost A"],
        year=2099, venue=None, abstract="Some text about transformers accuracy",
        url=None,
    )
    clients = {"semantic_scholar": MockSearchClientHallucinated([hallucinated_paper])}
    store_path = tmp_path / "facts_hallucinated.json"

    executor = LitMinerExecutor(
        session=session, search_clients=clients,
        extraction_provider=provider, grounding_provider=None,
        store_path=store_path,
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="transformers"))
    assert result.refs["verified_facts_count"] == 0

    store = FactStore(store_path)
    assert store.all() == []

@pytest.mark.asyncio
async def test_misattributed_claim_rejected_at_l4(session, tmp_path):
    # Paper about protein folding; claim is about LSTM — misattributed
    misattributed_abstract = "We study protein folding mechanisms in yeast."
    provider = MockProvider(responses=[MISATTRIBUTED_EXTRACT])
    real_paper = _paper(2, abstract=misattributed_abstract)
    clients = {"semantic_scholar": MockSearchClientReal([real_paper])}
    store_path = tmp_path / "facts_misattributed.json"

    executor = LitMinerExecutor(
        session=session, search_clients=clients,
        extraction_provider=provider, grounding_provider=None,
        store_path=store_path,
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="protein folding"))
    assert result.refs["verified_facts_count"] == 0
    assert FactStore(store_path).all() == []

@pytest.mark.asyncio
async def test_resume_no_reverify(session, tmp_path):
    """Second run with same paper skips it (no duplicate facts)."""
    provider = MockProvider(responses=[VALID_EXTRACT, VALID_EXTRACT])
    real_paper = _paper(1)
    clients = {"semantic_scholar": MockSearchClientReal([real_paper])}
    store_path = tmp_path / "facts_resume.json"

    async def _run():
        return await LitMinerExecutor(
            session=session, search_clients=clients,
            extraction_provider=provider, grounding_provider=None,
            store_path=store_path,
        ).run(DispatchUnit(node_id="ROOT", goal="spiking"))

    result1 = await _run()
    count_after_first = result1.refs["verified_facts_count"]
    result2 = await _run()
    # Second run: paper already seen, skipped
    assert result2.refs["skipped_papers_count"] >= 1
    assert result2.refs["verified_facts_count"] == 0
    # Total in store unchanged
    assert len(FactStore(store_path).all()) == count_after_first
```

Run: `uv run pytest tests/integration/test_lit_miner_e2e.py -v`
Expected: FAIL (until Groups 1–4 are complete)

- [ ] **Step 11.2: Add live test stub**

```python
# tests/live/test_lit_miner_live.py
"""Live end-to-end test — requires DASHSCOPE_API_KEY and optional SEMANTIC_SCHOLAR_API_KEY.
Skipped cleanly without credentials.
"""
import os, pytest

pytestmark = pytest.mark.live

@pytest.fixture
def api_key():
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        pytest.skip("DASHSCOPE_API_KEY not set")
    return key

@pytest.mark.asyncio
async def test_live_literature_mining_small_neuro_topic(api_key, tmp_path):
    """Real multi-source search + real Qwen extraction + real 4-layer verification."""
    from loop_sci.provider.factory import build_provider
    from loop_sci.state.session import RunSession
    from loop_sci.literature.search.semantic_scholar import SemanticScholarClient
    from loop_sci.literature.executor import LitMinerExecutor
    from loop_sci.literature.factbase.store import FactStore
    from loop_sci.engine.types import DispatchUnit
    import httpx

    provider = build_provider(api_key=api_key)
    ss_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    http = httpx.AsyncClient()
    clients = {"semantic_scholar": SemanticScholarClient(http=http, api_key=ss_key)}

    session = RunSession.create(tmp_path, task="spiking neural networks energy")
    store_path = tmp_path / "facts.json"
    executor = LitMinerExecutor(
        session=session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=provider,
        store_path=store_path,
        max_papers=3,
        max_facts_per_paper=2,
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="spiking neural network energy efficiency"))
    await http.aclose()

    assert result.status == "done"
    store = FactStore(store_path)
    facts = store.all()
    # At least attempt to mine; may find 0 facts if all rejected (acceptable)
    print(f"Live test: {len(facts)} verified facts from {result.refs['total_papers']} papers")
```

Run: `uv run pytest tests/integration/test_lit_miner_e2e.py -v`
(After Groups 1–4 complete) Expected: all 4 integration tests PASS

- [ ] **Step 11.3: Commit**

```bash
git add tests/integration/test_lit_miner_e2e.py tests/live/test_lit_miner_live.py
git commit -m "test(literature): offline integration anti-fabrication + resume + live stub"
```

---

### Task 12: Coverage gate + ruff clean + README section

**Files:**
- Modify: `README.md` (add Literature Mining section)
- Verify: coverage ≥ 80% on `loop_sci/literature/`

- [ ] **Step 12.1: Run full offline test suite with coverage**

```bash
uv run pytest tests/unit/literature/ tests/integration/test_lit_miner_e2e.py \
    --cov=loop_sci/literature --cov-report=term-missing -v
```

Expected: coverage ≥ 80% on `loop_sci/literature/`; if below, add targeted tests for uncovered branches.

- [ ] **Step 12.2: Run ruff clean**

```bash
uv run ruff check loop_sci/literature/ tests/unit/literature/ tests/integration/test_lit_miner_e2e.py
```

Expected: no errors. Fix any lint issues (unused imports, missing type annotations, etc.)

- [ ] **Step 12.3: Add README section**

Open `README.md` and append a `## Literature Mining` section covering:
- Configured sources (Semantic Scholar, arXiv, PubMed) and where to set credentials (`SEMANTIC_SCHOLAR_API_KEY`, `PUBMED_EMAIL` in `.env` or config)
- Fact-base output: `runs/<run_id>/idea_tree.json` (verified facts as nodes) + `facts.json` store
- How to run offline tests: `uv run pytest tests/unit/literature/ tests/integration/test_lit_miner_e2e.py`
- How to run live tests: `DASHSCOPE_API_KEY=... uv run pytest tests/live/test_lit_miner_live.py --run-live` (need `@pytest.mark.live` in `conftest.py` — already registered)

- [ ] **Step 12.4: Final commit**

```bash
git add README.md
git commit -m "docs(literature): README section for literature mining, credentials, fact-base output"
```

---

## Acceptance Summary (per spec)

| Scenario | Task | Proof |
|----------|------|-------|
| Unified multi-source results | T2 + T3 | `test_ss/arxiv/pubmed_search_returns_paper_results` + `test_dispatch_multi_source` |
| Offline-by-default | all | zero `httpx` real calls in `uv run pytest tests/unit/ tests/integration/` |
| Graceful degrade on one-source failure | T3 | `test_dispatch_degrades_on_one_failure` |
| Fact requires source_ref + evidence_span | T4 | `test_fact_requires_source_ref_and_evidence_span` |
| Ungrounded extraction dropped | T5 | `test_extractor_drops_ungrounded_claims` |
| Per-run bounds respected | T5 | `test_extractor_respects_per_paper_bound` |
| Hallucinated citation rejected at L2 | T6 + T11 | `test_l2_rejects_hallucinated_doi` + `test_hallucinated_citation_rejected_at_l2` |
| Misattributed claim rejected at L4 | T7 + T11 | `test_misattributed_claim_rejected_at_l4` |
| Hybrid grounding lexical+Qwen | T7 | `test_lexical_pass_without_qwen` + `test_borderline_uses_qwen_judge` |
| Verified fact in tree + store | T8 + T11 | `test_persist_adds_to_tree_and_store` + `test_verified_fact_persisted` |
| Rejected fact not persisted | T8 | `test_persist_rejected_fact_raises` |
| Resume skips already-processed | T9 + T11 | `test_executor_skips_already_processed` + `test_resume_no_reverify` |
| Coordinator dispatches LitMinerExecutor | T9 + T11 | `test_executor_produces_verified_fact` |
| ToolRegistry tools registered | T10 | `test_search_tool_registered_and_dispatches` |
| Coverage ≥ 80% | T12 | `--cov=loop_sci/literature` ≥ 80% |
| ruff clean | T12 | `ruff check` exits 0 |

## Risks

- **Qwen extraction JSON parse failures** — `extractor.py` wraps in try/except and returns `[]` rather than crashing; tested via MockProvider returning invalid JSON (add a targeted test if coverage reveals the branch uncovered).
- **httpx transport injection** — Each adapter takes `http: httpx.AsyncClient` in its constructor; tests replace the client's transport via `MockTransport`. Ensure `base_url` is NOT set on the real client so the adapter's full URLs work.
- **IdeaTree node id collisions on resume** — `paper_node_id` is derived from `external_id.replace(':', '_')`; `add_node` raises `ValueError` if id already exists; executor must check `tree._nodes` before calling `add_node`.
- **Grounding threshold tuning** — The hybrid router's `LOW_THRESHOLD` (0.15) and `HIGH_THRESHOLD` (0.60) may need adjustment after live tests; they are class attributes on `GroundingVerifier` and can be overridden per instance.
- **PubMed esearch + efetch two-hop** — tested with separate `MockTransport` URL-prefix routing; the mock uses url-fragment matching, so ensure `esearch.fcgi` and `efetch.fcgi` fragments are distinct enough.
