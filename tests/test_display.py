"""How the engine shows a scenario's quantities without knowing what they mean."""

import math

from scenariopaths import SCENARIOS

from casus import display
from casus.scenario import Scenario

SMOKE = Scenario.load(SCENARIOS / "smoke")


def _with_language(language):
    return Scenario.from_parts({**SMOKE.data, "language": language}, SMOKE.rules_source)


def test_a_label_comes_from_the_display_block_in_the_scenario_language():
    assert display.label(_with_language("es"), "supplies") == "suministros"


def test_a_label_falls_back_to_the_identifier_made_readable():
    assert display.label(SMOKE, "some_resource") == "some resource"


def test_a_band_is_the_first_bound_the_value_is_below():
    bands = SMOKE.display["bands"]["supplies"]
    bounds = sorted(float(b) for b in bands)
    assert display.band(SMOKE, "supplies", bounds[0] - 1) == bands[min(bands, key=float)]
    assert display.band(SMOKE, "supplies", 10_000) == bands[math.inf]


def test_an_unbanded_quantity_has_no_band():
    assert display.band(SMOKE, "stamina", 50.0) is None


def test_a_banded_value_hides_the_number_when_not_exact():
    assert display.shown(SMOKE, "supplies", 12.0, exact=False) == display.band(
        SMOKE, "supplies", 12.0
    )
    assert "12" in display.shown(SMOKE, "supplies", 12.0, exact=True)


def test_map_coordinates_are_hidden_by_default():
    assert {"lat", "lon"} <= set(display.hidden(SMOKE))
