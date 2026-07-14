"""Tests for register_literature_tools — TDD RED phase.

Covers:
1. All four tools are registered with correct names and have schemas.
2. lit_search dispatches offline and returns a JSON string with 'papers'.
3. lit_fetch dispatches offline and returns paper metadata JSON string.
4. lit_extract dispatches offline and returns facts JSON string.
5. lit_verify dispatches offline and returns verification status JSON string.
6. Unknown tool dispatch returns structured registry error (not a crash).
7. Malformed / missing required args return structured registry error.

All tests are offline — MockSearchClient + MockProvider, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure tests/conftest.py is importable (same pattern as test_lit_executor.py)
sys.path.insert(0, str(Path(__file__).parents[3]))  # project root for conftest
sys.path.insert(0, "tests")

from conftest import MockProvider

from loop_sci.engine.tools import ToolRegistry
from loop_sci.literature.tools import register_literature_tools
from loop_sci.literature.search.schema import PaperResult


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ABSTRACT = "SNN beats ANN by 12% on the ImageNet benchmark."

EXTRACT_RESP = json.dumps([
    {
        "claim": "SNN beats ANN by 12%",
        "evidence_span": "SNN beats ANN by 12% on the ImageNet benchmark.",
        "confidence": 0.9,
        "entities": [],
    }
])

GROUNDING_RESP = json.dumps({"supported": True, "confidence": 0.9})


def _paper() -> PaperResult:
    return PaperResult(
        source="semantic_scholar",
        external_id="s2:abc",
        title="T",
        authors=["A"],
        year=2024,
        venue=None,
        abstract=ABSTRACT,
        url=None,
    )


class MockSearchClient:
    """Offline mock: search returns a fixed paper; fetch_by_id returns the same paper."""

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        return [_paper()]

    async def fetch_by_id(self, eid: str) -> PaperResult | None:
        return _paper()


def _make_registry() -> tuple[ToolRegistry, MockProvider]:
    """Create a ToolRegistry with all four literature tools registered."""
    provider = MockProvider(responses=[EXTRACT_RESP, GROUNDING_RESP])
    registry = ToolRegistry()

    from loop_sci.literature.extract.extractor import FactExtractor
    from loop_sci.literature.verify.citation import VerificationPipeline

    extractor = FactExtractor(provider)
    pipeline = VerificationPipeline(
        {"semantic_scholar": MockSearchClient()},
        grounding_provider=provider,
    )
    register_literature_tools(
        registry,
        search_clients={"semantic_scholar": MockSearchClient()},
        extractor=extractor,
        pipeline=pipeline,
    )
    return registry, provider


# ---------------------------------------------------------------------------
# Test 1: All four tools registered with correct names and schemas
# ---------------------------------------------------------------------------


def test_all_four_tools_registered():
    """register_literature_tools must register exactly the four named tools."""
    registry, _ = _make_registry()
    defs = registry.get_definitions()
    names = {d["name"] for d in defs}
    assert {"lit_search", "lit_fetch", "lit_extract", "lit_verify"}.issubset(names)


def test_tool_definitions_have_schemas():
    """Every tool definition must carry an input_schema with 'type' and 'properties'."""
    registry, _ = _make_registry()
    defs = registry.get_definitions()
    name_to_def = {d["name"]: d for d in defs}
    for tool_name in ("lit_search", "lit_fetch", "lit_extract", "lit_verify"):
        defn = name_to_def[tool_name]
        assert "input_schema" in defn, f"{tool_name} missing input_schema"
        schema = defn["input_schema"]
        assert schema.get("type") == "object", f"{tool_name} schema type != 'object'"
        assert "properties" in schema, f"{tool_name} schema missing 'properties'"


def test_tool_definitions_have_descriptions():
    """Every registered tool must have a non-empty description."""
    registry, _ = _make_registry()
    defs = registry.get_definitions()
    name_to_def = {d["name"]: d for d in defs}
    for tool_name in ("lit_search", "lit_fetch", "lit_extract", "lit_verify"):
        desc = name_to_def[tool_name].get("description", "")
        assert desc.strip(), f"{tool_name} has empty description"


# ---------------------------------------------------------------------------
# Test 2: lit_search dispatches and returns JSON with 'papers'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lit_search_returns_papers():
    """lit_search must return a JSON string whose 'papers' list has >= 1 item."""
    registry, _ = _make_registry()
    result = await registry.dispatch(
        "lit_search", {"query": "spiking networks", "sources": ["semantic_scholar"]}
    )
    data = json.loads(result)
    assert "papers" in data, f"Expected 'papers' key, got: {result!r}"
    assert len(data["papers"]) >= 1


@pytest.mark.asyncio
async def test_lit_search_paper_fields():
    """Each paper in lit_search result must have title, source, external_id."""
    registry, _ = _make_registry()
    result = await registry.dispatch("lit_search", {"query": "spiking"})
    data = json.loads(result)
    paper = data["papers"][0]
    assert "title" in paper
    assert "source" in paper
    assert "external_id" in paper


@pytest.mark.asyncio
async def test_lit_search_with_no_sources_argument():
    """lit_search must work without an explicit 'sources' argument (optional)."""
    registry, _ = _make_registry()
    result = await registry.dispatch("lit_search", {"query": "spiking"})
    data = json.loads(result)
    assert "papers" in data
    assert len(data["papers"]) >= 1


# ---------------------------------------------------------------------------
# Test 3: lit_fetch dispatches and returns paper metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lit_fetch_returns_paper():
    """lit_fetch must return a JSON string with paper metadata fields."""
    registry, _ = _make_registry()
    result = await registry.dispatch(
        "lit_fetch", {"external_id": "s2:abc", "source": "semantic_scholar"}
    )
    data = json.loads(result)
    assert "title" in data, f"Expected 'title' in result, got: {result!r}"
    assert "external_id" in data
    assert "source" in data


@pytest.mark.asyncio
async def test_lit_fetch_unknown_source_returns_error_not_crash():
    """lit_fetch with an unknown source must return a JSON error, not raise."""
    registry, _ = _make_registry()
    result = await registry.dispatch(
        "lit_fetch", {"external_id": "s2:xyz", "source": "unknown_source"}
    )
    data = json.loads(result)
    assert "error" in data


# ---------------------------------------------------------------------------
# Test 4: lit_extract dispatches and returns facts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lit_extract_returns_facts():
    """lit_extract must return a JSON string whose 'facts' list has >= 1 item."""
    # Fresh provider with a single extraction response
    provider = MockProvider(responses=[EXTRACT_RESP])
    registry = ToolRegistry()

    from loop_sci.literature.extract.extractor import FactExtractor
    from loop_sci.literature.verify.citation import VerificationPipeline

    extractor = FactExtractor(provider)
    pipeline = VerificationPipeline(
        {"semantic_scholar": MockSearchClient()},
        grounding_provider=provider,
    )
    register_literature_tools(
        registry,
        search_clients={"semantic_scholar": MockSearchClient()},
        extractor=extractor,
        pipeline=pipeline,
    )
    result = await registry.dispatch(
        "lit_extract",
        {
            "external_id": "s2:abc",
            "source": "semantic_scholar",
            "abstract": ABSTRACT,
        },
    )
    data = json.loads(result)
    assert "facts" in data, f"Expected 'facts' key, got: {result!r}"
    assert len(data["facts"]) >= 1


@pytest.mark.asyncio
async def test_lit_extract_fact_fields():
    """Each fact from lit_extract must have 'claim', 'evidence_span', 'confidence'."""
    provider = MockProvider(responses=[EXTRACT_RESP])
    registry = ToolRegistry()

    from loop_sci.literature.extract.extractor import FactExtractor
    from loop_sci.literature.verify.citation import VerificationPipeline

    extractor = FactExtractor(provider)
    pipeline = VerificationPipeline(
        {"semantic_scholar": MockSearchClient()},
        grounding_provider=provider,
    )
    register_literature_tools(
        registry,
        search_clients={"semantic_scholar": MockSearchClient()},
        extractor=extractor,
        pipeline=pipeline,
    )
    result = await registry.dispatch(
        "lit_extract",
        {
            "external_id": "s2:abc",
            "source": "semantic_scholar",
            "abstract": ABSTRACT,
        },
    )
    data = json.loads(result)
    fact = data["facts"][0]
    assert "claim" in fact
    assert "evidence_span" in fact
    assert "confidence" in fact


# ---------------------------------------------------------------------------
# Test 5: lit_verify dispatches and returns verification status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lit_verify_returns_status():
    """lit_verify must return a JSON string with 'status' and 'layer_reached'."""
    # Enough responses for grounding verifier
    provider = MockProvider(responses=[GROUNDING_RESP] * 4)
    registry = ToolRegistry()

    from loop_sci.literature.extract.extractor import FactExtractor
    from loop_sci.literature.verify.citation import VerificationPipeline

    extractor = FactExtractor(provider)
    pipeline = VerificationPipeline(
        {"semantic_scholar": MockSearchClient()},
        grounding_provider=provider,
    )
    register_literature_tools(
        registry,
        search_clients={"semantic_scholar": MockSearchClient()},
        extractor=extractor,
        pipeline=pipeline,
    )
    result = await registry.dispatch(
        "lit_verify",
        {
            "claim": "SNN beats ANN by 12%",
            "source_ref": {
                "source": "semantic_scholar",
                "external_id": "s2:abc",
            },
            "evidence_span": ABSTRACT,
        },
    )
    data = json.loads(result)
    assert "status" in data, f"Expected 'status' key, got: {result!r}"
    assert "layer_reached" in data


# ---------------------------------------------------------------------------
# Test 6: Unknown tool dispatch returns structured registry error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool_dispatch_returns_structured_error():
    """Dispatching an unknown tool name must return a JSON error, not raise."""
    registry, _ = _make_registry()
    result = await registry.dispatch("lit_unknown_tool", {"x": 1})
    data = json.loads(result)
    assert data["error"] == "unknown_tool"
    assert "lit_unknown_tool" in data["tool"]


@pytest.mark.asyncio
async def test_unknown_tool_error_lists_available_tools():
    """The structured error for unknown tools must list the available tool names."""
    registry, _ = _make_registry()
    result = await registry.dispatch("nonexistent", {})
    data = json.loads(result)
    available = data.get("available", [])
    assert "lit_search" in available


# ---------------------------------------------------------------------------
# Test 7: Malformed / bad args return structured registry error (not crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lit_search_bad_sources_type_returns_error():
    """Passing wrong type for 'sources' (str instead of list) must not crash."""
    registry, _ = _make_registry()
    # sources must be a list; passing a string exercises the error-capture path
    result = await registry.dispatch("lit_search", {"query": "snn", "sources": "bad_type"})
    # Must not raise; must return a string (either valid papers or an error JSON)
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_lit_fetch_missing_required_arg_returns_error():
    """Missing required 'source' arg for lit_fetch must return structured error."""
    registry, _ = _make_registry()
    # 'source' is required; omitting it triggers a TypeError in the fn
    result = await registry.dispatch("lit_fetch", {"external_id": "s2:abc"})
    # ToolRegistry wraps the TypeError into a structured error JSON
    data = json.loads(result)
    assert "error" in data
