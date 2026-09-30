"""Scenarios are directories: data in YAML, physics in Python."""

import json
import pathlib
import random
import re
import subprocess
import sys
import textwrap

import pytest
import yaml
from scenariopaths import SCENARIOS

from casus import proxy
from casus.resolver import resolve
from casus.scenario import Scenario, ScenarioError, ScenarioInvalid
from casus.state import Action
from helpers import SMOKE_REGION_BLOCKS, SMOKE_REGION_GRAPH, smoke_with_regions, write_regions

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


def _scenario_with(tmp_path, bad_import=False, direct_assignment=False, touches=None):
    body = "from casus.ruleset import rule\n"
    if bad_import:
        body += "import os\n"
    body += '\n@rule(phase="contest")\ndef r(s):\n'
    if direct_assignment:
        body += '    s.place("p").infra = 5\n'
    if touches:
        body += f"    s.place({touches!r})\n"
    body += "    pass\n"
    return _write(tmp_path, _minimal(), rules=body)


def test_an_invalid_scenario_reports_all_of_its_findings_at_once(tmp_path):
    """Reporting one finding per load turns a five-minute fix into five loads,
    and the design agent pays that cost on every iteration."""
    with pytest.raises(ScenarioInvalid) as excinfo:
        Scenario.load(_scenario_with(tmp_path, bad_import=True, direct_assignment=True))
    assert {f.code for f in excinfo.value.findings} == {"forbidden-import", "direct-assignment"}


def test_loading_runs_the_dry_turn_as_well(tmp_path):
    with pytest.raises(ScenarioInvalid) as excinfo:
        Scenario.load(_scenario_with(tmp_path, touches="atlantis"))
    assert [f.code for f in excinfo.value.findings] == ["unknown-place"]


def test_a_scenario_rebuilt_from_a_transcript_is_still_checked_statically():
    with pytest.raises(ScenarioInvalid):
        Scenario.from_parts(_minimal(), "import os\n")


def test_an_entity_in_an_unknown_place_is_refused(tmp_path):
    data = _minimal(entities=[{"id": "e", "owner": "A", "kind": "unit", "place": "atlantis"}])
    with pytest.raises(ScenarioError, match="unknown place 'atlantis'"):
        Scenario.load(_write(tmp_path, data))


def test_an_adjacency_to_an_unknown_place_is_refused(tmp_path):
    data = _minimal(places={"p": {"name": "P", "owner": "A", "adjacency": ["shangri-la"]}})
    with pytest.raises(ScenarioError, match="unknown place 'shangri-la'"):
        Scenario.load(_write(tmp_path, data))


def test_a_duplicate_entity_id_is_refused(tmp_path):
    entity = {"id": "e", "owner": "A", "kind": "unit", "place": "p"}
    with pytest.raises(ScenarioError, match="duplicate entity id"):
        Scenario.load(_write(tmp_path, _minimal(entities=[entity, dict(entity)])))


def test_an_actor_without_a_briefing_is_refused(tmp_path):
    data = _minimal()
    data["actors"]["A"].pop("briefing")
    with pytest.raises(ScenarioError, match="has no briefing"):
        Scenario.load(_write(tmp_path, data))


def test_a_scenario_declares_its_language_and_defaults_to_english(tmp_path):
    data = _minimal()
    data.pop("language", None)
    assert Scenario.load(_write(tmp_path, data)).language() == "en"


# --- regions -------------------------------------------------------------------


def test_region_blocks_without_regions_json_fail_with_the_command(tmp_path):
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS)
    with pytest.raises(ScenarioError, match=re.escape(f"run: casus regions {directory}")):
        Scenario.load(directory, validate=False)


def test_a_stale_regions_json_fails_with_the_command(tmp_path):
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS)
    write_regions(directory, SMOKE_REGION_GRAPH)
    manifest = directory / "scenario.yaml"
    manifest.write_text(manifest.read_text().replace("XX-3", "XX-4"))
    with pytest.raises(ScenarioError, match="stale") as excinfo:
        Scenario.load(directory, validate=False)
    assert f"casus regions {directory}" in str(excinfo.value)


def test_the_computed_graph_fills_each_place_adjacency(tmp_path):
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS)
    write_regions(directory, SMOKE_REGION_GRAPH)
    world = Scenario.load(directory, validate=False).initial_state()
    assert {p: list(place.adjacency) for p, place in world.places.items()} == SMOKE_REGION_GRAPH


def test_exceptions_add_and_remove_an_edge_at_both_ends(tmp_path):
    def exceptions(data):
        data["places"]["b-home"]["adjacency"] = {"add": ["r-home"], "remove": ["border"]}

    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS, change=exceptions)
    write_regions(directory, SMOKE_REGION_GRAPH)
    world = Scenario.load(directory, validate=False).initial_state()
    assert world.places["b-home"].adjacency == ("r-home",)
    assert world.places["r-home"].adjacency == ("b-home", "border")
    assert world.places["border"].adjacency == ("r-home",)


def test_a_plain_list_stays_authoritative_and_a_disagreement_is_a_warning(tmp_path):
    def listed(data):
        data["places"]["r-home"]["adjacency"] = ["border", "b-home"]

    directory = smoke_with_regions(
        tmp_path, SMOKE_REGION_BLOCKS, keep_lists=("r-home",), change=listed
    )
    write_regions(directory, SMOKE_REGION_GRAPH)
    scenario = Scenario.load(directory, validate=False)
    assert scenario.initial_state().places["r-home"].adjacency == ("border", "b-home")
    [warning] = scenario.warnings
    assert warning.code == "adjacency-differs" and "'r-home'" in warning.message


def test_a_plain_list_that_matches_the_geometry_is_silent(tmp_path):
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS, keep_lists=("border",))
    write_regions(directory, SMOKE_REGION_GRAPH)
    assert Scenario.load(directory, validate=False).warnings == ()


def test_an_exception_naming_an_unknown_place_fails(tmp_path):
    def exceptions(data):
        data["places"]["border"]["adjacency"] = {"add": ["nowhere"]}

    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS, change=exceptions)
    write_regions(directory, SMOKE_REGION_GRAPH)
    with pytest.raises(ScenarioError, match="unknown place 'nowhere'"):
        Scenario.load(directory, validate=False)


def test_from_parts_refuses_exceptions_it_cannot_resolve():
    data = yaml.safe_load((SMOKE / "scenario.yaml").read_text())
    data["places"]["border"]["adjacency"] = {"remove": ["b-home"]}
    with pytest.raises(ScenarioError, match="only Scenario.load applies them"):
        Scenario.from_parts(data, (SMOKE / "rules.py").read_text())


def test_a_scenario_with_regions_validates_and_carries_them(tmp_path):
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS)
    written = json.loads(write_regions(directory, SMOKE_REGION_GRAPH).read_text())
    scenario = Scenario.load(directory)
    assert scenario.regions == written


def test_loading_and_running_with_regions_never_import_shapely(tmp_path):
    """Running, replaying and bundling read regions.json. Only `casus regions`
    needs shapely and the map data."""
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS)
    write_regions(directory, SMOKE_REGION_GRAPH)
    script = textwrap.dedent(
        f"""
        import pathlib, sys
        from casus import bundle, engine
        from casus.scenario import Scenario
        from helpers import FakeEngine
        scenario = Scenario.load({str(directory)!r}, validate=False)
        out = pathlib.Path({str(tmp_path / "run.jsonl")!r})
        engines = {{a: FakeEngine() for a in scenario.actors}}
        engine.run(scenario, seed=1, out=out, engines=engines, turns=1)
        engine.replay(out)
        bundle.bundle(out, out.with_suffix(".html"))
        assert "shapely" not in sys.modules, "shapely was imported"
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        cwd=pathlib.Path(__file__).parent,
    )
    assert done.returncode == 0, done.stderr[-800:]
