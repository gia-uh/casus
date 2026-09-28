import json
import pathlib

from scenariopaths import PRIVATE_SCENARIOS, all_scenarios, requires_private

from casus.v1.scenario import Scenario

ROOT = pathlib.Path(__file__).parent.parent
WORLDMAP = ROOT / "ui" / "worldmap.json"


def _worldmap() -> dict:
    return json.loads(WORLDMAP.read_text())


@requires_private
def test_worldmap_covers_every_country_the_scenarios_reference():
    """Only private scenarios name real countries; the shipped smoke scenario
    uses invented ones on purpose."""
    worldmap = _worldmap()
    for path in PRIVATE_SCENARIOS:
        for iso in Scenario.load(path).country_codes():
            assert iso in worldmap["countries"], f"{path.name}: {iso} is not in worldmap.json"


def test_small_islands_survive_simplification():
    """A tolerance high enough to shrink the payload can also flatten a small
    island into a triangle, and small islands are what a maritime theatre is made
    of. Iceland is the check: recognisable, and not large enough to pass by
    accident."""
    path = _worldmap()["countries"]["IS"]
    assert len(path) > 180, "Iceland's path is suspiciously short"
    assert path.count("L") > 12, "Iceland simplified down to a handful of vertices"


def test_the_projection_is_declared_so_the_replayer_can_place_markers():
    projection = _worldmap()["projection"]
    assert projection["kind"] == "equirectangular"
    assert projection["width"] / projection["height"] == 2.0


def test_every_centroid_in_every_scenario_lands_inside_the_viewbox():
    worldmap = _worldmap()
    width, height = worldmap["projection"]["width"], worldmap["projection"]["height"]
    for path in all_scenarios():
        for region in Scenario.load(path).initial_state().regions.values():
            lat, lon = region.centroid
            x = (lon + 180.0) / 360.0 * width
            y = (90.0 - lat) / 180.0 * height
            assert 0 <= x <= width, f"{path.name}: {region.id} projects off horizontally"
            assert 0 <= y <= height, f"{path.name}: {region.id} projects off vertically"


def test_every_scenario_keeps_its_regions_in_one_theatre():
    """A transposed lat/lon pair still projects inside the viewBox, so bounds
    alone would not catch it. Regions that belong to one scenario have to sit
    within a plausible theatre of each other."""
    for path in all_scenarios():
        regions = list(Scenario.load(path).initial_state().regions.values())
        lats = [r.centroid[0] for r in regions]
        lons = [r.centroid[1] for r in regions]
        assert max(lats) - min(lats) < 40.0, f"{path.name} spans too much latitude"
        assert max(lons) - min(lons) < 60.0, f"{path.name} spans too much longitude"


def test_every_path_is_closed():
    for iso, path in _worldmap()["countries"].items():
        assert path.startswith("M"), f"{iso} does not start with a move"
        assert path.endswith("Z"), f"{iso} has an unclosed ring"


def test_the_asset_stays_small_enough_to_inline_in_one_html_file():
    size = WORLDMAP.stat().st_size
    assert size < 250_000, f"{size / 1024:.0f} KiB is too much to inline"


def test_the_asset_records_where_it_came_from():
    assert "Natural Earth" in _worldmap()["source"]
