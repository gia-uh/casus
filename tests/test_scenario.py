"""Scenarios are directories: data in YAML, physics in Python."""

import random
import textwrap

import pytest
import yaml
from scenariopaths import SCENARIOS

from casus import proxy
from casus.resolver import resolve
from casus.scenario import Scenario, ScenarioError
from casus.state import Action

SMOKE = SCENARIOS / "smoke"


def test_a_scenario_directory_yields_data_and_a_ruleset():
    s = Scenario.load(SMOKE)
    assert s.initial_state().turn == 1
    assert s.ruleset.for_phase("contest")
    assert s.language() == "en"


def test_the_initial_state_carries_what_the_yaml_declares():
    s = Scenario.load(SMOKE)
    world = s.initial_state()
    assert set(world.actors) == set(s.data["actors"])
    assert world.actors["BLUE"].resources["stamina"] == float(
        s.data["actors"]["BLUE"]["resources"]["stamina"]
    )
    assert [e.id for e in world.entities] == [e["id"] for e in s.data["entities"]]


def test_bounds_come_from_the_declarations():
    s = Scenario.load(SMOKE)
    declared = s.data["resources"]["stamina"]
    assert s.resource_bounds()["stamina"] == (declared["min"], declared["max"])


def _write(tmp_path, data, rules="from casus.ruleset import rule\n", name="world"):
    directory = tmp_path / name
    directory.mkdir()
    (directory / "scenario.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    if rules is not None:
        (directory / "rules.py").write_text(textwrap.dedent(rules))
    return directory


def _minimal(**overrides):
    data = {
        "name": "minimal",
        "resources": {"stamina": {"min": 0, "max": 100}},
        "actions": {"hold": {"fields": []}},
        "actors": {
            "A": {"name": "A", "model": "m", "briefing": "b", "resources": {"stamina": 50}},
        },
        "places": {"p": {"name": "P", "owner": "A"}},
    }
    data.update(overrides)
    return data


def test_a_named_ruleset_replaces_a_local_rules_file(tmp_path):
    _write(
        tmp_path,
        _minimal(),
        rules="""
        from casus.ruleset import rule

        @rule(phase="upkeep")
        def tick(s):
            pass
    """,
        name="shared",
    )
    directory = _write(tmp_path, _minimal(rules="shared"), rules=None)
    assert [r.name for r in Scenario.load(directory).ruleset.rules] == ["tick"]


def test_a_named_ruleset_that_does_not_exist_fails_naming_it(tmp_path):
    directory = _write(tmp_path, _minimal(rules="nowhere"), rules=None)
    with pytest.raises(ScenarioError, match="nowhere"):
        Scenario.load(directory)


def test_an_actor_resource_must_be_declared(tmp_path):
    data = _minimal()
    data["actors"]["A"]["resources"]["morale"] = 3
    with pytest.raises(ScenarioError, match="morale"):
        Scenario.load(_write(tmp_path, data))


def test_an_unknown_owner_is_refused_at_the_door(tmp_path):
    with pytest.raises(ScenarioError, match="owned by unknown actor 'Z'"):
        Scenario.load(_write(tmp_path, _minimal(places={"p": {"name": "P", "owner": "Z"}})))


def test_an_action_field_outside_the_vocabulary_is_refused(tmp_path):
    data = _minimal(actions={"hold": {"fields": ["region"]}})
    with pytest.raises(ScenarioError, match="region"):
        Scenario.load(_write(tmp_path, data))


def test_a_scenario_rebuilds_from_its_parts():
    s = Scenario.load(SMOKE)
    again = Scenario.from_parts(s.data, s.rules_source)
    assert again.initial_state().digest() == s.initial_state().digest()
    assert [r.name for r in again.ruleset.rules] == [r.name for r in s.ruleset.rules]


SURFACE = (
    "actor", "place", "entity", "actors", "places", "entities", "find", "actions",
    "add", "set", "transfer", "decay", "move", "spawn", "despawn",
    "emit", "happened", "reject", "rng",
)  # fmt: skip


def _recording(used, name, method):
    def wrapper(self, *args, **kwargs):
        used.add(name)
        return method(self, *args, **kwargs)

    return wrapper


def test_the_smoke_scenario_exercises_the_whole_rule_surface(monkeypatch):
    """The rest of the suite leans on the smoke scenario, so it has to touch
    every call a rule can make, and both hooks."""
    used: set[str] = set()
    for name in SURFACE:
        original = getattr(proxy.State, name)
        if isinstance(original, property):
            wrapped = property(
                lambda self, _n=name, _o=original: (used.add(_n), _o.fget(self))[1]
            )
        else:
            wrapped = _recording(used, name, original)
        monkeypatch.setattr(proxy.State, name, wrapped)

    s = Scenario.load(SMOKE)
    world = s.initial_state()
    rng = random.Random(3)
    script = [
        [Action("BLUE", "raid", place="border", intensity=3),
         Action("RED", "raid", place="b-home"),
         Action("BLUE", "resupply", target="RED")],
        [Action("RED", "deploy", place="border", entities=("red-1",)),
         Action("BLUE", "raid", place="border", intensity=3)],
        [Action("BLUE", "hold"), Action("RED", "hold")],
        [Action("BLUE", "hold"), Action("RED", "hold")],
    ]  # fmt: skip
    for actions in script:
        for actor in sorted(world.actors):
            state = proxy.State(world, rng, s.resource_bounds(), s.attribute_bounds())
            s.ruleset.offer(state.read_only("offer"), actor)
            s.ruleset.view(state.scratch(), actor)
        world, _, _ = resolve(world, actions, s.ruleset, rng, s.actions,
                              s.resource_bounds(), s.attribute_bounds())  # fmt: skip
    assert used == set(SURFACE), f"never used: {sorted(set(SURFACE) - used)}"
