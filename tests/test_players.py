"""What the model is shown, and what it is allowed to say.

The parsing tests that used to live here are gone with the code they covered:
lingo owns the call and the validation now, and `test_actions.py` covers the
shape of what may be said.
"""

import asyncio
import random

import pytest
from pydantic import ValidationError

from casus import rules
from casus.players import Player, build_prompt
from helpers import FakeEngine, make_actor, make_force, make_region, make_world


def _player(actor_id="DEF", briefing="You are the defender.", engine=None):
    return Player(
        actor_id=actor_id,
        briefing=briefing,
        model="qwen/qwen3-32b",
        engine=engine or FakeEngine(),
    )


def _decide(player, world, seed=1):
    prompt, legal = player.view(world, random.Random(seed))
    return asyncio.run(player.decide(world, prompt, legal))


# --- fog of war -------------------------------------------------------------


def test_the_prompt_shows_perturbed_enemy_strength_for_a_low_isr_actor():
    world = make_world(
        actors={"ATK": make_actor("ATK"), "DEF": make_actor("DEF", isr=0.1)},
        forces=(make_force("ATK", "naval", region="sea-1", strength=80.0),),
    )
    engine = FakeEngine()
    _decide(_player(engine=engine), world)
    assert "strength 80" not in engine.prompts[0], "the true strength must not leak"
    assert "(estimate)" in engine.prompts[0]


def test_an_actor_sees_its_own_forces_exactly():
    world = make_world(
        actors={"ATK": make_actor("ATK"), "DEF": make_actor("DEF", isr=0.0)},
        forces=(make_force("DEF", "ground", region="r1", strength=37.0),),
    )
    view = rules.perturb_view(world, "DEF", random.Random(3))
    assert next(f.strength for f in view.forces if f.owner == "DEF") == 37.0


def test_perturbation_is_never_zero_when_isr_is_imperfect():
    world = make_world(
        actors={"ATK": make_actor("ATK"), "DEF": make_actor("DEF", isr=0.3)},
        forces=(make_force("ATK", "naval", region="sea-1", strength=80.0),),
    )
    for seed in range(50):
        view = rules.perturb_view(world, "DEF", random.Random(seed))
        assert next(f.strength for f in view.forces if f.owner == "ATK") != 80.0


def test_perturbation_is_exact_at_perfect_isr():
    world = make_world(
        actors={"ATK": make_actor("ATK"), "DEF": make_actor("DEF", isr=1.0)},
        forces=(make_force("ATK", "naval", region="sea-1", strength=80.0),),
    )
    view = rules.perturb_view(world, "DEF", random.Random(1))
    assert next(f.strength for f in view.forces if f.owner == "ATK") == 80.0


def test_the_draw_is_ordered_before_the_call_so_two_runs_agree():
    """Determinism lives in `view`, concurrency in the caller. Two identical
    seeds must produce identical prompts even though the calls go out together."""
    world = make_world(forces=(make_force("ATK", "naval", region="sea-1"),))
    first, _ = _player().view(world, random.Random(9))
    second, _ = _player().view(world, random.Random(9))
    assert first == second


# --- entitlement ------------------------------------------------------------


def test_the_offered_list_excludes_types_the_actor_cannot_take():
    world = make_world(forces=())
    engine = FakeEngine()
    _decide(_player(engine=engine), world)
    # only the list line, not the instructions that follow it, which legitimately
    # use the words as examples
    offered = engine.prompts[0].split("ACTIONS AVAILABLE TO YOU THIS TURN")[1].splitlines()[1]
    for impossible in ("invade", "air_campaign", "blockade", "strike"):
        assert impossible not in offered


def test_the_schema_handed_to_lingo_only_contains_the_offered_types():
    world = make_world(forces=())
    engine = FakeEngine()
    _decide(_player(engine=engine), world)
    schema = engine.schemas[0].model_json_schema()
    names = set(schema.get("$defs", {}))
    assert not any(n.lower().startswith("invade") for n in names)


def test_a_declaration_the_actor_was_not_offered_is_refused_by_the_type():
    """The fake engine validates against the real schema, so a test that hands
    it an impossible declaration fails the way the provider would."""
    world = make_world(forces=())
    engine = FakeEngine(
        {"actions": [{"type": "invade", "region": "r1"}], "rationale": "", "assessment": ""}
    )
    with pytest.raises(ValidationError):
        _decide(_player(engine=engine), world)


def test_owning_ground_forces_puts_invade_on_the_list():
    world = make_world(forces=(make_force("DEF", "ground", region="r1"),))
    assert "invade" in rules.legal_action_types(world, "DEF")
    assert "air_campaign" not in rules.legal_action_types(world, "DEF")


# --- prompt content ---------------------------------------------------------


def test_the_prompt_carries_the_briefing_verbatim():
    engine = FakeEngine()
    _decide(
        _player(briefing="Hold the island. Never negotiate on sovereignty.", engine=engine),
        make_world(),
    )
    assert "Never negotiate on sovereignty." in engine.prompts[0]


def test_the_prompt_reports_last_turns_resolutions():
    from casus.state import Action

    world = make_world()
    resolved, _ = rules.resolve(world, [Action(actor="ATK", type="sanction")], random.Random(1))
    engine = FakeEngine()
    _decide(_player(engine=engine), resolved)
    assert "WHAT HAPPENED LAST TURN" in engine.prompts[0]
    assert "escalation" in engine.prompts[0]


def test_exact_fuel_of_other_actors_is_banded_not_disclosed():
    world = make_world(
        actors={"ATK": make_actor("ATK", fuel_days=123.0), "DEF": make_actor("DEF")},
    )
    engine = FakeEngine()
    _decide(_player(engine=engine), world)
    others = engine.prompts[0].split("OTHER ACTORS")[1].split("FORCES YOU CAN SEE")[0]
    assert "123" not in others
    assert "sufficient" in others


def test_the_prompt_states_which_regions_each_offensive_action_can_reach():
    """Added after the first live run: a 32B model repeated an out-of-reach air
    campaign three turns running with the map in front of it."""
    world = make_world(
        regions={
            "target": make_region("target", "DEF", adjacency=("sea-1",)),
            "far": make_region("far", "DEF"),
            "sea-1": make_region(
                "sea-1", "", terrain="sea", population=0, adjacency=("target",)
            ),
        },
        forces=(make_force("ATK", "air", region="sea-1"),),
    )
    engine = FakeEngine()
    _decide(_player(actor_id="ATK", briefing="You are the attacker.", engine=engine), world)
    offered = engine.prompts[0].split("ACTIONS AVAILABLE TO YOU THIS TURN")[1]
    assert "air_campaign can reach: sea-1, target" in offered


def test_the_prompt_states_the_reserves_still_available():
    world = make_world(
        actors={"ATK": make_actor("ATK"), "DEF": make_actor("DEF", reserve_pool=90.0)}
    )
    engine = FakeEngine()
    _decide(_player(engine=engine), world)
    assert "90,000 personnel" in engine.prompts[0]


def test_build_prompt_is_a_pure_function_of_what_it_is_given():
    world = make_world()
    a = build_prompt("DEF", "orders", world, ("hold",))
    b = build_prompt("DEF", "orders", world, ("hold",))
    assert a == b


# --- what comes back --------------------------------------------------------


def test_a_declaration_becomes_engine_actions_owned_by_the_actor():
    world = make_world(forces=(make_force("DEF", "ground", region="r1"),))
    engine = FakeEngine(
        {
            "actions": [{"type": "harden", "region": "r1"}, {"type": "statement"}],
            "rationale": "dig in and talk",
            "assessment": "they escalate",
        }
    )
    turn = _decide(_player(engine=engine), world)
    assert [a.type for a in turn.actions] == ["harden", "statement"]
    assert all(a.actor == "DEF" for a in turn.actions)
    assert turn.rationale == "dig in and talk"
    assert turn.declaration["actions"][0]["region"] == "r1"
