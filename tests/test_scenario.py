import pathlib
import re

import pytest
import yaml

from casus import rules
from casus.scenario import Scenario, ScenarioError

SCENARIOS = pathlib.Path(__file__).parent.parent / "scenarios"
CARIBBEAN = SCENARIOS / "caribbean-2026.yaml"
SOURCES_MD = SCENARIOS / "SOURCES.md"


def _source_slugs() -> set[str]:
    return set(re.findall(r"^- `([\w-]+)`", SOURCES_MD.read_text(), re.MULTILINE))


# --- provenance, the thing that lets a number survive a question ------------


def test_every_force_and_region_names_a_source_listed_in_sources_md():
    raw = yaml.safe_load(CARIBBEAN.read_text())
    slugs = _source_slugs()
    assert slugs, "SOURCES.md lists no slugs at all"

    for force in raw["forces"]:
        assert "source" in force, f"force {force.get('id')} has no source key"
        assert force["source"] in slugs, f"{force['source']} is not listed in SOURCES.md"
    for region_id, region in raw["regions"].items():
        assert "source" in region, f"region {region_id} has no source key"
        assert region["source"] in slugs, f"{region['source']} is not listed in SOURCES.md"


def test_sources_md_records_the_conflicts_between_its_own_sources():
    """Two of the sources contradict each other on Cuban strength. Reconciling
    them silently inside a coefficient would be the dishonest option."""
    text = SOURCES_MD.read_text()
    assert "Known conflicts between sources" in text
    assert "1,146,500" in text, "the paramilitary discrepancy must stay visible"


# --- the published figures have to survive the round trip -------------------


def test_the_far_strength_matches_the_published_figure():
    state = Scenario.load(CARIBBEAN).initial_state()
    regulars = sum(f.strength for f in state.forces_of("CU") if f.kind == "ground")
    troops = regulars * rules.TROOPS_PER_STRENGTH_POINT
    assert 55_000 <= troops <= 70_000, f"{troops:,.0f} regulars is off the published ~50,000"


def test_the_cuban_reserve_pool_matches_the_published_militia_figure():
    state = Scenario.load(CARIBBEAN).initial_state()
    pool = state.actors["CU"].reserve_pool * rules.TROOPS_PER_STRENGTH_POINT
    assert pool == 90_000


def test_cuba_starts_with_roughly_two_weeks_of_fuel():
    state = Scenario.load(CARIBBEAN).initial_state()
    assert 10 <= state.actors["CU"].fuel_days <= 25


def test_the_island_population_is_about_ten_million():
    state = Scenario.load(CARIBBEAN).initial_state()
    cuban = sum(r.population for r in state.regions.values() if r.country == "CU")
    assert 9_500_000 <= cuban <= 11_500_000


def test_holding_the_island_needs_about_two_hundred_thousand_security_personnel():
    """The rule and the scenario have to agree with the published estimate, or
    the invasion branch means nothing."""
    state = Scenario.load(CARIBBEAN).initial_state()
    cuban = sum(r.population for r in state.regions.values() if r.country == "CU")
    assert rules.occupation_requirement(cuban) // 2 >= 95_000


def test_guantanamo_starts_essentially_undefended():
    state = Scenario.load(CARIBBEAN).initial_state()
    garrison = sum(f.strength for f in state.forces_in("gtmo"))
    assert garrison < 10, "CSIS describes Guantanamo as essentially undefended"


def test_cuban_air_defences_are_weaker_than_the_air_force_attacking_them():
    state = Scenario.load(CARIBBEAN).initial_state()
    cuban_ad = sum(f.strength for f in state.forces_of("CU") if f.kind == "air_defense")
    us_air = sum(f.strength for f in state.forces_of("US") if f.kind == "air")
    assert cuban_ad < us_air / 3


# --- the map has to be playable ---------------------------------------------


def test_every_cuban_region_is_reachable_from_the_sea():
    state = Scenario.load(CARIBBEAN).initial_state()
    seas = {r.id for r in state.regions.values() if r.terrain == "sea"}
    for region in state.regions.values():
        if region.country != "CU":
            continue
        touches = set(region.adjacency) & seas
        neighbours = {
            n for adj in region.adjacency for n in state.regions[adj].adjacency if n in seas
        }
        assert touches or neighbours, f"{region.id} cannot be reached from any sea zone"


def test_adjacency_is_symmetric():
    """An asymmetric edge lets one side strike from cover, which is a modelling
    accident rather than a decision."""
    raw = yaml.safe_load(CARIBBEAN.read_text())
    for region_id, region in raw["regions"].items():
        for neighbour in region.get("adjacency") or ():
            back = raw["regions"][neighbour].get("adjacency") or ()
            assert region_id in back, f"{region_id} -> {neighbour} is one-way"


def test_the_invasion_branch_is_reachable_at_all():
    """Claim two in the spec is that the published branches emerge. A branch the
    engine cannot reach would be a gap in the model masquerading as a finding."""
    scenario = Scenario.load(CARIBBEAN)
    state = scenario.initial_state()
    assert "invade" in rules.legal_action_types(state, "US")
    assert state.actors["US"].reserve_pool > 100


def test_every_actor_has_a_briefing_naming_its_red_lines():
    scenario = Scenario.load(CARIBBEAN)
    for actor_id in scenario.actors:
        briefing = scenario.briefing(actor_id)
        assert "Red line" in briefing, f"{actor_id} has no stated red lines"
        assert len(briefing.split()) > 40, f"{actor_id}'s briefing is too thin to play"


def test_venezuela_is_a_condition_and_not_an_actor():
    scenario = Scenario.load(CARIBBEAN)
    assert "VE" not in scenario.actors
    assert "Maduro" in CARIBBEAN.read_text(), "the condition must be stated somewhere"


# --- validation -------------------------------------------------------------


def test_scenario_rejects_a_force_in_an_unknown_region():
    broken = yaml.safe_load(CARIBBEAN.read_text())
    broken["forces"][0]["region"] = "atlantis"
    with pytest.raises(ScenarioError, match="unknown region 'atlantis'"):
        Scenario.from_dict(broken)


def test_scenario_rejects_an_adjacency_to_an_unknown_region():
    broken = yaml.safe_load(CARIBBEAN.read_text())
    broken["regions"]["cu-habana"]["adjacency"] = ["shangri-la"]
    with pytest.raises(ScenarioError, match="unknown region 'shangri-la'"):
        Scenario.from_dict(broken)


def test_scenario_rejects_a_duplicate_force_id():
    broken = yaml.safe_load(CARIBBEAN.read_text())
    broken["forces"].append(dict(broken["forces"][0]))
    with pytest.raises(ScenarioError, match="duplicate force id"):
        Scenario.from_dict(broken)


def test_scenario_rejects_an_actor_without_a_briefing():
    broken = yaml.safe_load(CARIBBEAN.read_text())
    broken["actors"]["CU"].pop("briefing")
    with pytest.raises(ScenarioError, match="has no briefing"):
        Scenario.from_dict(broken)


def test_scenario_rejects_an_unknown_terrain():
    broken = yaml.safe_load(CARIBBEAN.read_text())
    broken["regions"]["cu-habana"]["terrain"] = "jungle"
    with pytest.raises(ScenarioError, match="unknown terrain 'jungle'"):
        Scenario.from_dict(broken)


def test_both_shipped_scenarios_load():
    for path in sorted(SCENARIOS.glob("*.yaml")):
        scenario = Scenario.load(path)
        assert scenario.initial_state().turn == 1, path.name
