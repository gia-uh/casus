import re

import pytest
import yaml
from scenariopaths import (
    PRIVATE_SCENARIOS,
    PRIVATE_SOURCES,
    SMOKE,
    all_scenarios,
    requires_private,
)

from casus import rules
from casus.scenario import Scenario, ScenarioError


def _slugs(path) -> set[str]:
    return set(re.findall(r"^- `([\w-]+)`", path.read_text(), re.MULTILINE))


# --- validation, against the scenario that always ships ---------------------


def test_every_shipped_and_linked_scenario_loads():
    for path in all_scenarios():
        assert Scenario.load(path).initial_state().turn == 1, path.name


def test_scenario_rejects_a_force_in_an_unknown_region():
    broken = yaml.safe_load(SMOKE.read_text())
    broken["forces"][0]["region"] = "atlantis"
    with pytest.raises(ScenarioError, match="unknown region 'atlantis'"):
        Scenario.from_dict(broken)


def test_scenario_rejects_an_adjacency_to_an_unknown_region():
    broken = yaml.safe_load(SMOKE.read_text())
    broken["regions"]["g-capital"]["adjacency"] = ["shangri-la"]
    with pytest.raises(ScenarioError, match="unknown region 'shangri-la'"):
        Scenario.from_dict(broken)


def test_scenario_rejects_a_duplicate_force_id():
    broken = yaml.safe_load(SMOKE.read_text())
    broken["forces"].append(dict(broken["forces"][0]))
    with pytest.raises(ScenarioError, match="duplicate force id"):
        Scenario.from_dict(broken)


def test_scenario_rejects_an_actor_without_a_briefing():
    broken = yaml.safe_load(SMOKE.read_text())
    broken["actors"]["GREEN"].pop("briefing")
    with pytest.raises(ScenarioError, match="has no briefing"):
        Scenario.from_dict(broken)


def test_scenario_rejects_an_unknown_terrain():
    broken = yaml.safe_load(SMOKE.read_text())
    broken["regions"]["g-capital"]["terrain"] = "jungle"
    with pytest.raises(ScenarioError, match="unknown terrain 'jungle'"):
        Scenario.from_dict(broken)


def test_scenario_rejects_a_force_owned_by_nobody():
    broken = yaml.safe_load(SMOKE.read_text())
    broken["forces"][0]["owner"] = "PURPLE"
    with pytest.raises(ScenarioError, match="unknown owner 'PURPLE'"):
        Scenario.from_dict(broken)


def test_adjacency_is_symmetric_in_every_scenario():
    """An asymmetric edge lets one side strike from cover, which is a modelling
    accident rather than a decision."""
    for path in all_scenarios():
        raw = yaml.safe_load(path.read_text())
        for region_id, region in raw["regions"].items():
            for neighbour in region.get("adjacency") or ():
                back = raw["regions"][neighbour].get("adjacency") or ()
                assert region_id in back, f"{path.name}: {region_id} -> {neighbour} is one-way"


def test_every_actor_states_its_red_lines_in_every_scenario():
    """A briefing that lists only objectives produces a player with no politics,
    which is the least interesting kind."""
    for path in all_scenarios():
        scenario = Scenario.load(path)
        for actor_id in scenario.actors:
            briefing = scenario.briefing(actor_id)
            assert "Red line" in briefing, f"{path.name}: {actor_id} has no red lines"
            assert len(briefing.split()) > 40, f"{path.name}: {actor_id}'s briefing is thin"


def test_every_populated_region_is_reachable_from_the_sea():
    for path in all_scenarios():
        state = Scenario.load(path).initial_state()
        seas = {r.id for r in state.regions.values() if r.terrain == "sea"}
        assert seas, f"{path.name} has no sea zone, so no force can arrive"
        for region in state.regions.values():
            if region.terrain == "sea" or not region.population:
                continue
            near = set(region.adjacency) & seas
            hop = {n for a in region.adjacency for n in state.regions[a].adjacency if n in seas}
            assert near or hop, f"{path.name}: {region.id} is unreachable from any sea"


# --- provenance, against whatever private scenarios are linked --------------


@requires_private
def test_every_force_and_region_names_a_source_listed_in_sources_md():
    slugs = _slugs(PRIVATE_SOURCES)
    assert slugs, "the SOURCES.md beside the private scenarios lists no slugs"
    for path in PRIVATE_SCENARIOS:
        raw = yaml.safe_load(path.read_text())
        for force in raw["forces"]:
            assert "source" in force, f"{path.name}: force {force.get('id')} has no source"
            assert force["source"] in slugs, f"{force['source']} is not in SOURCES.md"
        for region_id, region in raw["regions"].items():
            assert "source" in region, f"{path.name}: region {region_id} has no source"
            assert region["source"] in slugs, f"{region['source']} is not in SOURCES.md"


@requires_private
def test_sources_md_records_the_conflicts_between_its_own_sources():
    """Where sources disagree, reconciling them silently inside a coefficient is
    the dishonest option."""
    assert "Known conflicts between sources" in PRIVATE_SOURCES.read_text()


@requires_private
def test_a_private_scenario_can_reach_its_top_rung():
    """Claim two in the design is that the published branches emerge. A branch
    the engine cannot reach would be a gap in the model masquerading as a
    finding."""
    for path in PRIVATE_SCENARIOS:
        state = Scenario.load(path).initial_state()
        assert any(
            "invade" in rules.legal_action_types(state, actor) for actor in state.actors
        ), f"{path.name}: nobody can invade, so the top rung is unreachable"


@requires_private
def test_the_occupation_requirement_is_consistent_with_the_populations():
    """The rule and the scenario have to agree, or the occupation branch means
    nothing."""
    for path in PRIVATE_SCENARIOS:
        state = Scenario.load(path).initial_state()
        for region in state.regions.values():
            if region.population <= 0:
                continue
            required = rules.occupation_requirement(region.population)
            assert required > 0
            assert required == region.population // rules.INHABITANTS_PER_SECURITY_MEMBER


def test_a_scenario_declares_its_language_and_defaults_to_english():
    from casus.scenario import Scenario as S

    assert S.load(SMOKE).language() == "en"
    for path in PRIVATE_SCENARIOS:
        assert len(S.load(path).language()) >= 2


def test_the_language_reaches_the_prompt_the_model_is_given():
    """A rationale the room cannot read is a rationale the room cannot check."""
    from casus.players import system_prompt

    assert "Spanish" in system_prompt("es")
    assert "Spanish" not in system_prompt("en")
    assert system_prompt("en").endswith("`assessment`.")
