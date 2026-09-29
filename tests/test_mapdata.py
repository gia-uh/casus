"""The map data shipped in the package, and the one-shot tool that builds it."""

from __future__ import annotations

import importlib.util
import math
import pathlib

import pytest
import shapely
from shapely.geometry import box

from casus.geo import mapdata

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


def _payload(*provinces, countries=None) -> dict:
    tool = _tool()
    return {
        "version": "test",
        "scale": tool.SCALE,
        "countries": countries or {"AA": "Alpha"},
        "provinces": [tool.encode(*p) for p in provinces],
    }


def test_a_province_decodes_to_the_polygon_that_was_encoded():
    shape = shapely.Polygon([(0, 0), (2, 0), (2, 2), (0, 2)], [[(0.5, 0.5), (1, 0.5), (1, 1)]])
    decoded = mapdata.decode(_payload(("AA-1", "One", "AA", shape)))
    assert decoded.geoms["AA-1"].equals(shape)
    assert decoded.names["AA-1"] == "One"


def test_a_code_split_over_two_features_is_one_province():
    decoded = mapdata.decode(
        _payload(("AA-1", "One", "AA", box(0, 0, 1, 1)), ("AA-1", "One", "AA", box(1, 0, 2, 1)))
    )
    assert decoded.geoms["AA-1"].geom_type == "Polygon"
    assert decoded.geoms["AA-1"].area == pytest.approx(2.0)


def test_a_country_is_the_union_of_its_provinces():
    decoded = mapdata.decode(
        _payload(
            ("AA-1", "One", "AA", box(0, 0, 1, 1)),
            ("AA-2", "Two", "AA", box(1, 0, 2, 1)),
            ("BB-1", "Three", "BB", box(2, 0, 3, 1)),
            countries={"AA": "Alpha", "BB": "Beta"},
        )
    )
    assert mapdata.country("AA", decoded).equals(box(0, 0, 2, 1))
    assert mapdata.provinces(["AA-2", "BB-1"], decoded).equals(box(1, 0, 3, 1))


def test_the_land_inside_a_box_is_every_province_there_clipped_to_it():
    decoded = mapdata.decode(
        _payload(("AA-1", "One", "AA", box(0, 0, 1, 1)), ("AA-2", "Two", "AA", box(1, 0, 2, 1)))
    )
    assert decoded.land((0.5, 0.0, 3.0, 1.0)).equals(box(0.5, 0, 2, 1))


# --- the packaged data ---------------------------------------------------------


def test_the_packaged_data_names_its_version_and_is_decoded_once():
    data = mapdata.load_admin1()
    assert data.version.startswith("ne-10m-admin1-") and data.version.endswith("-t0.02")
    assert len(data.geoms) > 4000
    assert data is mapdata.load_admin1()


def test_the_packaged_coverage_is_valid():
    """No gap and no overlap between provinces, or the regions built from them
    would have one too."""
    assert shapely.coverage_is_valid(list(mapdata.load_admin1().geoms.values()))


@pytest.mark.parametrize("code", ["CU-03", "CU-16", "US-FL", "US-PR"])
def test_a_packaged_province_is_a_valid_polygon(code):
    shape = mapdata.provinces([code])
    assert shape.is_valid and not shape.is_empty


@pytest.mark.parametrize("code", ["CU", "US", "DO", "HT", "JM", "BS", "MX"])
def test_a_packaged_country_union_has_no_holes(code):
    shape = mapdata.country(code)
    assert shape.is_valid and not shape.is_empty
    assert sum(len(p.interiors) for p in shapely.get_parts(shape)) == 0


def test_havana_keeps_close_to_its_source_area():
    """Ciudad de la Habana is 728 km² in the source; 712 km² after compaction was
    measured on 2026-09-29."""
    shape = mapdata.provinces(["CU-03"])
    km2 = shape.area * 111.32**2 * math.cos(math.radians(23.1))
    assert 690 < km2 < 740
