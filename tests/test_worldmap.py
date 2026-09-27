import json
import pathlib

from casus.scenario import Scenario

ROOT = pathlib.Path(__file__).parent.parent
WORLDMAP = ROOT / "ui" / "worldmap.json"
CARIBBEAN = ROOT / "scenarios" / "caribbean-2026.yaml"


def _worldmap() -> dict:
    return json.loads(WORLDMAP.read_text())


def test_worldmap_covers_every_country_the_scenario_references():
    worldmap = _worldmap()
    for iso in Scenario.load(CARIBBEAN).country_codes():
        assert iso in worldmap["countries"], f"{iso} missing from worldmap.json"


def test_cubas_outline_survived_simplification():
    """A tolerance high enough to shrink the payload can also flatten a small
    island into a triangle. This is the island the class is looking at."""
    path = _worldmap()["countries"]["CU"]
    assert len(path) > 200, "Cuba's path is suspiciously short"
    assert path.count("L") > 12, "Cuba simplified down to a handful of vertices"


def test_the_projection_is_declared_so_the_replayer_can_place_markers():
    projection = _worldmap()["projection"]
    assert projection["kind"] == "equirectangular"
    assert projection["width"] / projection["height"] == 2.0


def test_every_centroid_in_the_scenario_lands_inside_the_viewbox():
    worldmap = _worldmap()
    width, height = worldmap["projection"]["width"], worldmap["projection"]["height"]
    for region in Scenario.load(CARIBBEAN).initial_state().regions.values():
        lat, lon = region.centroid
        x = (lon + 180.0) / 360.0 * width
        y = (90.0 - lat) / 180.0 * height
        assert 0 <= x <= width, f"{region.id} projects off the map horizontally"
        assert 0 <= y <= height, f"{region.id} projects off the map vertically"


def test_caribbean_centroids_sit_in_the_caribbean():
    """A transposed lat/lon pair still projects inside the viewBox, so bounds
    alone would not catch it. Every region in this scenario belongs in a box
    around the Caribbean."""
    for region in Scenario.load(CARIBBEAN).initial_state().regions.values():
        lat, lon = region.centroid
        assert 15.0 <= lat <= 30.0, f"{region.id} latitude {lat} is not Caribbean"
        assert -90.0 <= lon <= -70.0, f"{region.id} longitude {lon} is not Caribbean"


def test_every_path_is_closed():
    for iso, path in _worldmap()["countries"].items():
        assert path.startswith("M"), f"{iso} does not start with a move"
        assert path.endswith("Z"), f"{iso} has an unclosed ring"


def test_the_asset_stays_small_enough_to_inline_in_one_html_file():
    size = WORLDMAP.stat().st_size
    assert size < 250_000, f"{size / 1024:.0f} KiB is too much to inline"


def test_the_asset_records_where_it_came_from():
    assert "Natural Earth" in _worldmap()["source"]
