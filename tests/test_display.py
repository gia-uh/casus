"""How the engine shows a scenario's quantities without knowing what they mean."""

import math

import pytest
import yaml
from scenariopaths import SCENARIOS

from casus import display
from casus.scenario import Scenario

SMOKE = Scenario.load(SCENARIOS / "smoke")
SMOKE_RULES = SMOKE.rules_source


@pytest.fixture
def smoke_data() -> dict:
    return yaml.safe_load((SCENARIOS / "smoke" / "scenario.yaml").read_text())


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


def test_a_value_above_the_last_bound_gets_the_last_band_not_the_exact_figure():
    """The spec's own example ends at 1.0 without `.inf`; a value of 1.0 must not
    leak as a number to other actors."""
    data = {
        **SMOKE.data,
        "display": {**SMOKE.display, "bands": {"stamina": {30: "low", 60: "high"}}},
    }
    s = Scenario.from_parts(data, SMOKE.rules_source)
    assert display.shown(s, "stamina", 75.0, exact=False) == "high"


def _with_display(smoke_data, **block):
    data = {**smoke_data, "display": {**smoke_data.get("display", {}), **block}}
    return Scenario.from_parts(data, SMOKE_RULES)


def test_an_actor_label_comes_from_the_scenario_language(smoke_data):
    scenario = _with_display(
        {**smoke_data, "language": "es"}, labels={"es": {"BLUE": "Azules"}}
    )
    assert display.actor_label(scenario, "BLUE") == "Azules"


def test_an_actor_without_a_label_falls_back_to_its_name(smoke_data):
    scenario = _with_display(smoke_data, labels={})
    assert display.actor_label(scenario, "RED") == smoke_data["actors"]["RED"]["name"]


def test_a_place_label_falls_back_to_its_name_then_its_id(smoke_data):
    scenario = _with_display(smoke_data, labels={})
    assert display.place_label(scenario, "border") == smoke_data["places"]["border"]["name"]
    assert display.place_label(scenario, "nowhere") == "nowhere"


def test_card_and_worse_when_higher_default_to_empty(smoke_data):
    for key in ("card", "worse_when_higher"):
        smoke_data["display"].pop(key, None)
    scenario = _with_display(smoke_data)
    assert display.card(scenario) == ()
    assert display.worse_when_higher(scenario) == frozenset()


def test_card_and_worse_when_higher_read_the_block(smoke_data):
    scenario = _with_display(smoke_data, card=["infra"], worse_when_higher=["infra"])
    assert display.card(scenario) == ("infra",)
    assert display.worse_when_higher(scenario) == frozenset({"infra"})
