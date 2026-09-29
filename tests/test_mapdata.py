"""The map data shipped in the package, and the one-shot tool that builds it."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
import shapely
from shapely.geometry import box

ROOT = pathlib.Path(__file__).parent.parent
TOOL = ROOT / "tools" / "build_mapdata.py"


def _tool():
    """The tool is not part of the package, so the tests load it by path."""
    spec = importlib.util.spec_from_file_location("build_mapdata", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_tool_keeps_a_valid_coverage_valid():
    compacted = _tool().compact([box(0, 0, 1, 1), box(1, 0, 2, 1)])
    assert len(compacted) == 2
    assert shapely.coverage_is_valid(compacted)


def test_the_tool_fails_when_the_coverage_does_not_hold():
    tool = _tool()
    with pytest.raises(tool.CoverageInvalid, match="raise the tolerance"):
        tool.compact([box(0, 0, 2, 2), box(1, 0, 3, 2)])


def test_a_ring_is_stored_as_integer_steps_from_its_first_point():
    code, name, country, [[ring]] = _tool().encode("AA-1", "One", "AA", box(0, 0, 0.5, 0.25))
    assert (code, name, country) == ("AA-1", "One", "AA")
    assert all(isinstance(v, int) for v in ring)
    x, y = ring[0], ring[1]
    for dx, dy in zip(ring[2::2], ring[3::2], strict=True):
        x, y = x + dx, y + dy
    assert (x, y) == (ring[0], ring[1]), "the ring does not close"
