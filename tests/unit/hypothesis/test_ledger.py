"""Tests for loop_sci.hypothesis.ledger — append-only VerdictLedger."""
from __future__ import annotations

import json
from pathlib import Path

from loop_sci.hypothesis.ledger import VerdictLedger


def test_append_and_reload(tmp_path: Path) -> None:
    """Two appends produce two lines; first entry has correct verdict_id."""
    ledger = VerdictLedger(tmp_path / "ledger.jsonl")
    ledger.append("v1", "node-a", "qwen-plus", "UP", round_n=1)
    ledger.append("v2", "node-b", "qwen-plus", "DOWN", round_n=1)
    lines = (tmp_path / "ledger.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["verdict_id"] == "v1"


def test_accepted_node_ids(tmp_path: Path) -> None:
    """accepted_node_ids returns only UP-result node_ids."""
    ledger = VerdictLedger(tmp_path / "ledger.jsonl")
    ledger.append("v1", "node-a", "qwen-plus", "UP", round_n=1)
    ledger.append("v2", "node-b", "qwen-plus", "DOWN", round_n=1)
    assert ledger.accepted_node_ids() == {"node-a"}


def test_resume_loads_existing(tmp_path: Path) -> None:
    """VerdictLedger pre-loads an existing ledger file on construction."""
    p = tmp_path / "ledger.jsonl"
    p.write_text(
        json.dumps(
            {
                "verdict_id": "v0",
                "node_id": "n0",
                "reviewer_model": "qwen-plus",
                "result": "UP",
                "round": 0,
            }
        )
        + "\n"
    )
    ledger = VerdictLedger(p)
    assert "n0" in ledger.accepted_node_ids()


def test_append_only_does_not_rewrite_first_line(tmp_path: Path) -> None:
    """Second append accumulates; does not overwrite first line."""
    p = tmp_path / "ledger.jsonl"
    ledger1 = VerdictLedger(p)
    ledger1.append("v1", "node-a", "qwen-plus", "UP", round_n=1)

    # Open a second instance that pre-loads the existing file, then appends.
    ledger2 = VerdictLedger(p)
    ledger2.append("v2", "node-b", "qwen-plus", "DOWN", round_n=2)

    lines = p.read_text().strip().split("\n")
    assert len(lines) == 2, "Both entries must be present"
    assert json.loads(lines[0])["verdict_id"] == "v1"
    assert json.loads(lines[1])["verdict_id"] == "v2"


def test_round_field_recorded(tmp_path: Path) -> None:
    """round field is stored in each ledger entry."""
    ledger = VerdictLedger(tmp_path / "ledger.jsonl")
    ledger.append("v1", "node-a", "qwen-plus", "UP", round_n=3)
    raw = json.loads((tmp_path / "ledger.jsonl").read_text().strip())
    assert raw["round"] == 3


def test_all_entries_returns_list(tmp_path: Path) -> None:
    """all_entries returns all appended entries as a list of dicts."""
    ledger = VerdictLedger(tmp_path / "ledger.jsonl")
    ledger.append("v1", "node-a", "qwen-plus", "UP", round_n=1)
    ledger.append("v2", "node-b", "qwen-plus", "DOWN", round_n=2)
    entries = ledger.all_entries()
    assert len(entries) == 2
    assert entries[0]["node_id"] == "node-a"
    assert entries[1]["node_id"] == "node-b"


def test_malformed_trailing_line_skipped(tmp_path: Path) -> None:
    """A trailing malformed line is silently skipped rather than crashing."""
    p = tmp_path / "ledger.jsonl"
    good_entry = json.dumps(
        {
            "verdict_id": "v0",
            "node_id": "n0",
            "reviewer_model": "qwen-plus",
            "result": "UP",
            "round": 0,
        }
    )
    p.write_text(good_entry + "\n" + "{broken json\n")
    ledger = VerdictLedger(p)
    # The good entry is loaded; the broken line is skipped without crash.
    assert "n0" in ledger.accepted_node_ids()
    assert len(ledger.all_entries()) == 1
