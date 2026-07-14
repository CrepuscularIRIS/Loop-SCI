"""Smoke tests: verify loop_sci is importable and package metadata resolves."""

import importlib
import importlib.metadata


def test_loop_sci_importable():
    """Package loop_sci must be importable after installation."""
    mod = importlib.import_module("loop_sci")
    assert mod is not None


def test_package_metadata_resolves():
    """Package metadata for loop-sci must be resolvable via importlib.metadata."""
    meta = importlib.metadata.metadata("loop-sci")
    assert meta["Name"] == "loop-sci"
    assert meta["Version"] is not None


def test_package_version_format():
    """Package version must follow semver-like format (x.y.z)."""
    version = importlib.metadata.version("loop-sci")
    parts = version.split(".")
    assert len(parts) == 3, f"Expected 3-part version, got: {version}"
    assert all(p.isdigit() for p in parts), f"Non-numeric version parts: {version}"
