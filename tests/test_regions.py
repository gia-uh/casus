"""Regions from region blocks, on a small synthetic coverage so no test depends
on real borders. One test at the end reads the packaged data."""

from __future__ import annotations

import itertools
import json
import math

import pytest
import shapely
from shapely.geometry import Point, box, shape

from casus.geo import regions
from casus.geo.mapdata import MapData
from casus.geo.regions import compute, region_digest

#: Five 2° squares near the equator. AA-1..AA-4 are a 2×2 block, country AA; BB-1
#: lies east of AA-2, country BB, and touches AA-4 only at the corner (4, 2).
#: Everything else in the theatre is water.
CELLS = {
    "AA-1": box(0, 0, 2, 2),
    "AA-2": box(2, 0, 4, 2),
    "AA-3": box(0, 2, 2, 4),
    "AA-4": box(2, 2, 4, 4),
    "BB-1": box(4, 0, 6, 2),
}
THEATRE = {"theatre": [-2, -2, 8, 6]}


def squares() -> MapData:
    return MapData(
        version="squares",
        geoms=dict(CELLS),
        names={code: f"Square {code}" for code in CELLS},
        country_of={code: code[:2] for code in CELLS},
        countries={"AA": "Alpha", "BB": "Beta"},
    )


def _compute(places: dict, display: dict | None = None) -> regions.Regions:
    return compute(places, THEATRE if display is None else display, mapdata=squares())


def _shape(result: regions.Regions, place: str):
    return shape({"type": "MultiPolygon", "coordinates": result.places[place]["polygon"]})


def _km2(geom) -> float:
    lat = math.radians(geom.centroid.y)
    return geom.area * regions.KM_PER_DEGREE**2 * math.cos(lat)


def test_a_place_on_provinces_takes_their_union():
    result = _compute({"west": {"region": {"provinces": ["AA-1", "AA-3"]}}})
    assert result.findings == []
    assert _shape(result, "west").equals(box(0, 0, 2, 4))
    assert result.places["west"]["kind"] == "provinces"


def test_two_places_on_one_province_split_it_between_their_seeds():
    result = _compute(
        {
            "west": {"region": {"provinces": ["AA-1"], "seed": [1.0, 0.5]}},
            "east": {"region": {"provinces": ["AA-1"], "seed": [1.0, 1.5]}},
        }
    )
    assert result.findings == []
    assert _shape(result, "west").equals(box(0, 0, 1, 2))
    assert _shape(result, "east").equals(box(1, 0, 2, 2))
    assert result.places["west"]["label"] == [0.5, 1.0]


def test_a_place_on_a_country_takes_all_of_it():
    result = _compute({"alpha": {"region": {"country": "AA"}}})
    assert _shape(result, "alpha").equals(box(0, 0, 4, 4))
    assert result.places["alpha"]["kind"] == "country"


def test_two_places_on_one_country_split_it_without_overlap():
    result = _compute(
        {
            "south": {"region": {"country": "AA", "seed": [1.0, 1.0]}},
            "north": {"region": {"country": "AA", "seed": [3.0, 3.0]}},
        }
    )
    south, north = _shape(result, "south"), _shape(result, "north")
    assert south.area == pytest.approx(8.0) and north.area == pytest.approx(8.0)
    assert south.intersection(north).area == pytest.approx(0.0)
    assert south.union(north).equals(box(0, 0, 4, 4))


def test_the_same_provinces_in_another_order_are_the_same_base():
    result = _compute(
        {
            "a": {"region": {"provinces": ["AA-1", "AA-2"], "seed": [1.0, 1.0]}},
            "b": {"region": {"provinces": ["AA-2", "AA-1"], "seed": [1.0, 3.0]}},
        }
    )
    assert result.findings == []
    assert _shape(result, "a").equals(box(0, 0, 2, 2))


def test_a_sea_zone_is_water_cut_to_its_reach():
    result = _compute({"gulf": {"region": {"sea": [1.0, -1.0], "reach_km": 50}}})
    gulf = _shape(result, "gulf")
    assert result.places["gulf"]["kind"] == "sea"
    assert gulf.intersection(box(0, 0, 6, 4)).area == pytest.approx(0.0)
    assert _km2(gulf) == pytest.approx(math.pi * 50**2, rel=0.02)
    assert result.places["gulf"]["label"] == [-1.0, 1.0]


def test_two_sea_zones_split_the_water_between_them():
    result = _compute(
        {
            "west": {"region": {"sea": [1.0, -1.0], "reach_km": 600}},
            "east": {"region": {"sea": [1.0, 7.0], "reach_km": 600}},
        }
    )
    west, east = _shape(result, "west"), _shape(result, "east")
    assert west.intersection(east).area == pytest.approx(0.0)
    assert west.bounds[2] == pytest.approx(3.0) and east.bounds[0] == pytest.approx(3.0)


def test_a_site_is_a_disc_carved_out_of_the_region_it_sits_in():
    result = _compute(
        {
            "land": {"region": {"provinces": ["AA-1"]}},
            "base": {"region": {"site": [1.0, 1.0], "radius_km": 20}},
        }
    )
    assert result.findings == []
    base, land = _shape(result, "base"), _shape(result, "land")
    assert result.places["base"]["kind"] == "site"
    assert _km2(base) == pytest.approx(math.pi * 20**2, rel=0.02)
    assert not land.contains(Point(1.0, 1.0))
    assert land.area == pytest.approx(4.0 - base.area, rel=1e-3)


def test_a_site_without_a_radius_takes_the_default():
    result = _compute({"base": {"region": {"site": [1.0, -1.0]}}})
    radius = regions.DEFAULT_RADIUS_KM
    assert _km2(_shape(result, "base")) == pytest.approx(math.pi * radius**2, rel=0.02)


def test_a_label_point_lies_inside_its_region():
    result = _compute({"ell": {"region": {"provinces": ["AA-1", "AA-2", "AA-4"]}}})
    assert _shape(result, "ell").contains(Point(result.places["ell"]["label"]))


def test_the_theatre_is_the_bounding_box_of_every_region_with_a_margin():
    result = compute({"west": {"region": {"provinces": ["AA-1"]}}}, {}, mapdata=squares())
    m = regions.MARGIN_DEGREES
    assert result.theatre == (-m, -m, 2 + m, 2 + m)


def test_the_scenario_can_set_the_theatre():
    result = _compute({"west": {"region": {"provinces": ["AA-1"]}}})
    assert result.theatre == (-2.0, -2.0, 8.0, 6.0)


def test_the_land_outline_is_every_province_in_the_theatre_clipped_to_it():
    """BB-1 is no place and is still drawn: land for context."""
    result = _compute({"west": {"region": {"provinces": ["AA-1"]}}}, {"theatre": [1, 1, 5, 3]})
    land = shape({"type": "MultiPolygon", "coordinates": result.land})
    assert land.bounds == (1.0, 1.0, 5.0, 3.0)
    assert land.area == pytest.approx(7.0)
    assert _shape(result, "west").equals(box(1, 1, 2, 2))


def test_regions_json_has_the_shape_the_viewer_reads():
    result = _compute(
        {
            "west": {"region": {"provinces": ["AA-1"]}},
            "gulf": {"region": {"sea": [1.0, -1.0], "reach_km": 50}},
        }
    )
    doc = result.to_json("abc")
    keys = {"version", "mapdata", "digest", "theatre", "land", "places", "adjacency"}
    assert set(doc) == keys
    assert (doc["version"], doc["mapdata"]) == (regions.VERSION, "squares")
    assert doc["digest"] == "abc"
    assert set(doc["places"]["west"]) == {"polygon", "label", "kind"}
    assert all(type(v) is float for v in doc["theatre"])
    coords = shapely.get_coordinates(_shape(result, "gulf")).flatten()
    assert all(round(v, regions.DECIMALS) == v for v in coords)
    json.dumps(doc)


def test_the_digest_follows_the_region_blocks_and_the_theatre_only():
    places = {"a": {"name": "A", "region": {"provinces": ["AA-1"]}}, "b": {"name": "B"}}
    reordered = {"b": {"name": "Renamed"}, "a": {"region": {"provinces": ["AA-1"]}}}
    assert region_digest(places) == region_digest(reordered)
    moved = {**places, "a": {"region": {"provinces": ["AA-2"]}}}
    assert region_digest(moved) != region_digest(places)
    assert region_digest(places, [0, 0, 1, 1]) != region_digest(places)


@pytest.mark.parametrize(
    "places",
    [
        {"x": "region"},
        {"g": {"region": {"sea": [1.0, -1.0], "reach_km": math.nan}}},
        {"g": {"region": {"sea": [1.0, -1.0], "reach_km": math.inf}}},
    ],
)
def test_a_malformed_place_is_no_region_and_does_not_raise(places):
    assert _compute(places).places == {}


def _codes(result: regions.Regions) -> list[str]:
    return [f.code for f in result.findings]


def test_an_unknown_province_names_the_provinces_of_its_country():
    result = _compute({"x": {"region": {"provinces": ["AA-9"]}}})
    [finding] = result.findings
    assert (finding.place, finding.code) == ("x", "unknown-province")
    assert "AA-4 (Square AA-4)" in finding.message
    assert "x" not in result.places


def test_an_unknown_country_names_the_closest_codes():
    [finding] = _compute({"x": {"region": {"country": "AB"}}}).findings
    assert finding.code == "unknown-country"
    assert "AA (Alpha)" in finding.message


def test_a_seed_outside_its_own_base_is_a_finding():
    result = _compute({"x": {"region": {"provinces": ["AA-1"], "seed": [3.0, 3.0]}}})
    assert _codes(result) == ["seed-outside-base"]
    assert result.places == {}


def test_two_places_on_one_base_need_a_seed_each():
    result = _compute(
        {
            "x": {"region": {"provinces": ["AA-2"], "seed": [1.0, 3.0]}},
            "y": {"region": {"provinces": ["AA-2"]}},
        }
    )
    assert [(f.place, f.code) for f in result.findings] == [("y", "missing-seed")]
    assert result.places == {}


@pytest.mark.parametrize("offset", [0.0, 1e-9, 0.005])
def test_near_coincident_seeds_are_a_finding(offset):
    """GEOS raises on coincident seeds and returns cells that do not split the base
    for nearly coincident ones. Either way the answer is a finding: never an
    exception, never an empty polygon. 0.005° is about 0.56 km here."""
    result = _compute(
        {
            "x": {"region": {"provinces": ["AA-1"], "seed": [1.0, 1.0]}},
            "y": {"region": {"provinces": ["AA-1"], "seed": [1.0, 1.0 + offset]}},
            "z": {"region": {"provinces": ["AA-4"]}},
        }
    )
    assert _codes(result) == ["seeds-too-close"]
    assert set(result.places) == {"z"}
    assert all(p["polygon"] for p in result.places.values())


def test_seed_on_a_border_belongs_to_one_region():
    """A seed exactly on the border between two bases is on its own base (the
    boundary counts), the regions around it never overlap, and a site on that
    border is the one region that holds the point."""
    result = _compute(
        {
            "west-a": {"region": {"provinces": ["AA-1"], "seed": [1.0, 2.0]}},
            "west-b": {"region": {"provinces": ["AA-1"], "seed": [1.0, 0.5]}},
            "east": {"region": {"provinces": ["AA-2"]}},
            "post": {"region": {"site": [1.0, 2.0], "radius_km": 10}},
        }
    )
    assert result.findings == []
    shapes = {p: _shape(result, p) for p in result.places}
    assert set(shapes) == {"west-a", "west-b", "east", "post"}
    assert all(not s.is_empty for s in shapes.values())
    for p, q in itertools.combinations(shapes, 2):
        assert shapes[p].intersection(shapes[q]).area == pytest.approx(0.0, abs=1e-9), (p, q)
    assert [p for p, s in shapes.items() if s.contains(Point(2.0, 1.0))] == ["post"]
    assert shapes["west-a"].contains(Point(result.places["west-a"]["label"]))


def test_a_region_carved_away_entirely_is_a_finding():
    result = _compute(
        {
            "land": {"region": {"provinces": ["AA-1"]}},
            "base": {"region": {"site": [1.0, 1.0], "radius_km": 300}},
        }
    )
    assert [(f.place, f.code) for f in result.findings] == [("land", "empty-region")]
    assert set(result.places) == {"base"}


def test_a_region_smaller_than_a_site_is_a_finding():
    result = _compute({"x": {"region": {"sea": [1.0, -1.0], "reach_km": 5}}})
    assert _codes(result) == ["region-too-small"]


def test_a_site_in_no_region_and_no_water_is_a_finding():
    """BB-1 is land, and no place claims it."""
    result = _compute({"base": {"region": {"site": [1.0, 5.0]}}})
    assert _codes(result) == ["site-outside"]


def test_latlon_that_disagrees_with_the_region_is_a_finding():
    result = _compute(
        {"x": {"region": {"provinces": ["AA-1"]}, "attrs": {"lat": 1.0, "lon": 7.0}}}
    )
    assert _codes(result) == ["latlon-disagrees"]


def test_latlon_inside_the_region_is_not_a_finding():
    result = _compute(
        {"x": {"region": {"provinces": ["AA-1"]}, "attrs": {"lat": 1.0, "lon": 1.0}}}
    )
    assert result.findings == []


@pytest.mark.parametrize("lat", [math.inf, math.nan, True])
def test_latlon_that_is_not_a_finite_number_is_not_checked(lat):
    result = _compute(
        {"x": {"region": {"provinces": ["AA-1"]}, "attrs": {"lat": lat, "lon": 7.0}}}
    )
    assert result.findings == []
    assert set(result.places) == {"x"}


@pytest.mark.parametrize(
    "block",
    [
        {},
        {"provinces": ["AA-1"], "country": "AA"},
        {"provinces": "AA-1"},
        {"site": [1.0]},
        {"sea": [1.0, -1.0], "reach_km": -5},
        "AA-1",
    ],
)
def test_a_malformed_region_block_is_a_finding(block):
    assert _codes(_compute({"x": {"region": block}})) == ["bad-region"]


def test_a_malformed_theatre_is_a_finding():
    result = _compute({"x": {"region": {"provinces": ["AA-1"]}}}, {"theatre": [5, 0, 1, 1]})
    assert _codes(result) == ["bad-theatre"]
