"""One language model per actor, speaking a type it cannot misuse, from a
prompt built out of the scenario's display block."""

import asyncio
import dataclasses
import random

import pytest
from pydantic import ValidationError
from scenariopaths import SCENARIOS

from casus import display
from casus.players import Player, build_prompt
from casus.scenario import Scenario
from casus.state import Actor, Event
from helpers import FakeEngine

SMOKE = Scenario.load(SCENARIOS / "smoke")


def _player(actor="BLUE", reply=None, scenario=SMOKE):
    return Player(actor_id=actor, scenario=scenario, engine=FakeEngine(reply))


def _view(actor="BLUE", seed=1, world=None):
    return _player(actor).view(world or SMOKE.initial_state(), random.Random(seed))


def _strength_line(prompt, entity):
    return next(line for line in prompt.splitlines() if line.strip().startswith(f"{entity}:"))


def test_the_prompt_is_built_from_the_display_block():
    prompt, _ = _view()
    assert display.label(SMOKE, "stamina") in prompt
    assert "fuel" not in prompt


def test_an_actor_sees_its_own_units_exactly_and_others_through_the_view():
    world = SMOKE.initial_state()
    seen, offered = _view(world=world)
    truth = build_prompt("BLUE", SMOKE, world, offered)
    own = next(e for e in world.entities if e.owner == "BLUE")
    foreign = next(e for e in world.entities if e.owner == "RED")
    assert _strength_line(seen, own.id) == _strength_line(truth, own.id)
    assert _strength_line(seen, foreign.id) != _strength_line(truth, foreign.id)


def test_the_draw_is_ordered_before_the_call_so_two_runs_agree():
    assert _view(seed=4)[0] == _view(seed=4)[0]
    assert _view(seed=4)[0] != _view(seed=5)[0]


def test_the_view_never_changes_the_world():
    world = SMOKE.initial_state()
    _view(world=world)
    assert world.digest() == SMOKE.initial_state().digest()


def test_the_offer_decides_what_is_on_the_list():
    world = SMOKE.initial_state()
    poor = dataclasses.replace(
        world,
        actors={**world.actors, "RED": Actor(id="RED", name="Red", resources={"supplies": 1.0,
                                                                            "stamina": 60.0})},
    )  # fmt: skip
    _, offered = _view("RED", world=poor)
    assert "resupply" not in offered
    _, offered = _view("BLUE", world=poor)
    assert "resupply" in offered


def test_the_schema_handed_to_lingo_only_contains_the_offered_types():
    player = _player()
    prompt, offered = player.view(SMOKE.initial_state(), random.Random(1))
    asyncio.run(player.decide(SMOKE.initial_state(), prompt, offered))
    schema = player.engine.schemas[0].model_json_schema()
    consts = {d["properties"]["type"]["const"] for d in schema["$defs"].values()}
    assert consts == set(offered)


def test_a_declaration_the_actor_was_not_offered_is_refused_by_the_type():
    player = _player(reply={"actions": [{"type": "teleport"}], "rationale": "", "assessment": ""})
    prompt, offered = player.view(SMOKE.initial_state(), random.Random(1))
    with pytest.raises(ValidationError):
        asyncio.run(player.decide(SMOKE.initial_state(), prompt, offered))


def test_the_prompt_carries_the_briefing_verbatim():
    prompt, _ = _view()
    assert SMOKE.briefing("BLUE").strip() in prompt


def test_the_prompt_reports_last_turns_events():
    world = dataclasses.replace(
        SMOKE.initial_state(),
        events=(Event("raided", {"actor": "RED", "place": "b-home", "reason": "it burned"}),),
    )
    prompt, _ = _view(world=world)
    assert "it burned" in prompt.split("WHAT HAPPENED LAST TURN")[1]


def test_a_banded_resource_of_another_actor_is_not_disclosed_exactly():
    world = SMOKE.initial_state()
    red_supplies = world.actors["RED"].resources["supplies"]
    prompt, _ = _view(world=world)
    others = prompt.split("OTHER ACTORS")[1].split("\n\n")[0]
    assert display.band(SMOKE, "supplies", red_supplies) in others
    assert f"{red_supplies:.0f}" not in others


def test_the_prompt_states_where_each_placed_action_can_go():
    prompt, offered = _view()
    raid_line = next(line for line in prompt.splitlines() if line.strip().startswith("raid"))
    for place in offered["raid"]:
        assert place in raid_line


def test_build_prompt_is_a_pure_function_of_what_it_is_given():
    world = SMOKE.initial_state()
    offered = {"hold": None}
    assert build_prompt("BLUE", SMOKE, world, offered) == build_prompt(
        "BLUE", SMOKE, world, offered
    )


def test_a_declaration_becomes_engine_actions_owned_by_the_actor():
    player = _player(reply={"actions": [{"type": "hold"}], "rationale": "r", "assessment": "a"})
    prompt, offered = player.view(SMOKE.initial_state(), random.Random(1))
    turn = asyncio.run(player.decide(SMOKE.initial_state(), prompt, offered))
    assert [(a.actor, a.type) for a in turn.actions] == [("BLUE", "hold")]
    assert (turn.rationale, turn.assessment) == ("r", "a")
