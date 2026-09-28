"""The scenarios that run on the reference ruleset: the shipped reference
scenario, and whatever private class scenarios are linked.

The provenance checks run when `scenarios/private` resolves and skip when it
does not. A class scenario whose figures have no sources should fail the suite
of whoever maintains it, even though it never ships with the engine.
"""

import re

import yaml
from reference_rules import MODULE
from scenariopaths import PRIVATE, PRIVATE_DIRS, SCENARIOS, requires_private_dirs

from casus.players import offered_actions
from casus.scenario import Scenario

PRIVATE_SOURCES = PRIVATE / "SOURCES.md"


def _on_reference():
    dirs = [SCENARIOS / "reference", *PRIVATE_DIRS]
    return [d for d in dirs if (yaml.safe_load((d / "scenario.yaml").read_text()).get("rules")
                                in (None, "reference"))]  # fmt: skip


def _slugs(path) -> set[str]:
    return set(re.findall(r"^- `([\w-]+)`", path.read_text(), re.MULTILINE))


def test_adjacency_is_symmetric_in_every_scenario():
    """An asymmetric edge lets one side strike from cover, which is a modelling
    accident rather than a decision."""
    for path in [SCENARIOS / "smoke", *_on_reference()]:
        places = yaml.safe_load((path / "scenario.yaml").read_text())["places"]
        for place_id, place in places.items():
            for neighbour in place.get("adjacency") or ():
                back = places[neighbour].get("adjacency") or ()
                assert place_id in back, f"{path.name}: {place_id} -> {neighbour} is one-way"


def test_every_actor_states_its_red_lines():
    """A briefing that lists only objectives produces a player with no politics,
    which is the least interesting kind."""
    for path in _on_reference():
        scenario = Scenario.load(path, validate=False)
        for actor_id in scenario.actors:
            assert "Red line" in scenario.briefing(actor_id), f"{path.name}: {actor_id}"


def test_every_populated_place_is_reachable_from_the_sea():
    for path in _on_reference():
        world = Scenario.load(path, validate=False).initial_state()
        seas = {p.id for p in world.places.values() if p.attrs.get("terrain") == "sea"}
        assert seas, f"{path.name} has no sea zone, so no force can arrive"
        for place in world.places.values():
            if place.attrs.get("terrain") == "sea" or not place.attrs.get("population"):
                continue
            near = set(place.adjacency) & seas
            hop = {n for a in place.adjacency for n in world.places[a].adjacency if n in seas}
            assert near or hop, f"{path.name}: {place.id} is unreachable from any sea"


@requires_private_dirs
def test_every_entity_and_place_names_a_source_listed_in_sources_md():
    slugs = _slugs(PRIVATE_SOURCES)
    assert slugs, "the SOURCES.md beside the private scenarios lists no slugs"
    for path in PRIVATE_DIRS:
        raw = yaml.safe_load((path / "scenario.yaml").read_text())
        for entity in raw["entities"]:
            assert entity.get("source") in slugs, f"{path.name}: entity {entity['id']}"
        for place_id, place in raw["places"].items():
            assert place.get("source") in slugs, f"{path.name}: place {place_id}"


@requires_private_dirs
def test_sources_md_records_the_conflicts_between_its_own_sources():
    """Where sources disagree, reconciling them silently inside a coefficient is
    the dishonest option."""
    assert "Known conflicts between sources" in PRIVATE_SOURCES.read_text()


@requires_private_dirs
def test_a_private_scenario_can_reach_its_top_rung():
    """A branch the engine cannot reach would be a gap in the model masquerading
    as a finding."""
    import random

    for path in PRIVATE_DIRS:
        scenario = Scenario.load(path, validate=False)
        world = scenario.initial_state()
        assert any(
            "invade" in offered_actions(scenario, world, actor, random.Random(0))
            for actor in scenario.actors
        ), f"{path.name}: nobody can invade, so the top rung is unreachable"


@requires_private_dirs
def test_the_occupation_requirement_is_consistent_with_the_populations():
    for path in PRIVATE_DIRS:
        world = Scenario.load(path, validate=False).initial_state()
        for place in world.places.values():
            population = int(place.attrs.get("population") or 0)
            if population <= 0:
                continue
            required = MODULE.occupation_requirement(population)
            assert required == population // MODULE.INHABITANTS_PER_SECURITY_MEMBER > 0


@requires_private_dirs
def test_a_private_scenario_declares_its_language():
    for path in PRIVATE_DIRS:
        assert len(Scenario.load(path, validate=False).language()) >= 2
