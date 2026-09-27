import random

import pytest

from casus import rules
from casus.llm import LLMResult
from casus.players import (
    MAX_ACTIONS_PER_TURN,
    Player,
    SchemaViolation,
    extract_json,
    parse_declaration,
)
from casus.state import Action
from helpers import make_actor, make_force, make_region, make_world


def _result(text: str) -> LLMResult:
    return LLMResult(
        text=text, raw={"stub": True}, model="m", prompt_tokens=1, completion_tokens=1
    )


def _returns(text: str):
    def call(model, messages, schema=None, temperature=0.7):
        return _result(text)

    return call


def _capture(
    seen: dict, text: str = '{"actions":[{"type":"hold"}],"rationale":"r","assessment":"a"}'
):
    def call(model, messages, schema=None, temperature=0.7):
        seen["prompt"] = messages[-1]["content"]
        seen["messages"] = messages
        seen["schema"] = schema
        return _result(text)

    return call


def _player(actor_id="CU", briefing="You are Cuba.") -> Player:
    return Player(actor_id=actor_id, briefing=briefing, model="qwen/qwen3-32b")


# --- the schema-failure path ------------------------------------------------


def test_prose_response_retries_once_then_falls_back_to_hold():
    calls = []

    def flaky(model, messages, schema=None, temperature=0.7):
        calls.append(messages)
        return _result("I think we should wait and see how Washington reacts.")

    turn = _player().decide(make_world(), random.Random(1), call=flaky)

    assert len(calls) == 2, "exactly one retry"
    assert "valid JSON" in calls[1][-1]["content"]
    assert [a.type for a in turn.actions] == ["hold"]
    assert turn.schema_failures == 2
    assert turn.actions[0].actor == "CU"


def test_the_retry_quotes_the_actual_validation_error_back():
    calls = []

    def flaky(model, messages, schema=None, temperature=0.7):
        calls.append(messages)
        return _result('{"actions": [{"type": "orbital_bombardment"}]}')

    _player().decide(make_world(), random.Random(1), call=flaky)
    assert "orbital_bombardment" in calls[1][-1]["content"]


def test_a_valid_reply_on_the_second_attempt_is_accepted():
    replies = iter(
        [
            "sorry, thinking out loud",
            '{"actions":[{"type":"statement"}],"rationale":"buy time","assessment":"they wait"}',
        ]
    )

    def call(model, messages, schema=None, temperature=0.7):
        return _result(next(replies))

    turn = _player().decide(make_world(), random.Random(1), call=call)
    assert [a.type for a in turn.actions] == ["statement"]
    assert turn.schema_failures == 1
    assert turn.rationale == "buy time"


def test_decide_never_raises_even_on_an_empty_completion():
    turn = _player().decide(make_world(), random.Random(1), call=_returns(""))
    assert [a.type for a in turn.actions] == ["hold"]


# --- fog of war -------------------------------------------------------------


def test_prompt_shows_perturbed_enemy_strength_for_a_low_isr_actor():
    world = make_world(
        actors={"US": make_actor("US"), "CU": make_actor("CU", isr=0.1)},
        forces=(make_force("US", "naval", region="sea-1", strength=80.0),),
    )
    seen: dict = {}
    _player().decide(world, random.Random(5), call=_capture(seen))

    assert "strength 80" not in seen["prompt"], "the true strength must not leak"
    assert "(estimate)" in seen["prompt"]


def test_a_high_isr_actor_sees_a_number_close_to_the_truth():
    def seen_strength(isr):
        world = make_world(
            actors={"US": make_actor("US"), "CU": make_actor("CU", isr=isr)},
            forces=(make_force("US", "naval", region="sea-1", strength=80.0),),
        )
        view = rules.perturb_view(world, "CU", random.Random(5))
        return next(f.strength for f in view.forces if f.owner == "US")

    assert abs(seen_strength(0.95) - 80.0) < abs(seen_strength(0.1) - 80.0)


def test_an_actor_sees_its_own_forces_exactly():
    world = make_world(
        actors={"US": make_actor("US"), "CU": make_actor("CU", isr=0.0)},
        forces=(make_force("CU", "ground", region="r1", strength=37.0),),
    )
    view = rules.perturb_view(world, "CU", random.Random(3))
    assert next(f.strength for f in view.forces if f.owner == "CU") == 37.0


def test_perturbation_is_never_zero_when_isr_is_imperfect():
    """A perturbation that can come out as exactly zero hands a blind actor the
    truth at random, which would make the fog tests flaky rather than wrong."""
    world = make_world(
        actors={"US": make_actor("US"), "CU": make_actor("CU", isr=0.3)},
        forces=(make_force("US", "naval", region="sea-1", strength=80.0),),
    )
    for seed in range(50):
        view = rules.perturb_view(world, "CU", random.Random(seed))
        assert next(f.strength for f in view.forces if f.owner == "US") != 80.0


def test_perturbation_is_exact_at_perfect_isr():
    world = make_world(
        actors={"US": make_actor("US"), "CU": make_actor("CU", isr=1.0)},
        forces=(make_force("US", "naval", region="sea-1", strength=80.0),),
    )
    view = rules.perturb_view(world, "CU", random.Random(1))
    assert next(f.strength for f in view.forces if f.owner == "US") == 80.0


# --- entitlement ------------------------------------------------------------


def test_legal_action_list_in_the_prompt_excludes_types_the_actor_cannot_take():
    world = make_world(forces=())
    seen: dict = {}
    _player().decide(world, random.Random(1), call=_capture(seen))

    offered = seen["prompt"].split("ACTIONS AVAILABLE TO YOU THIS TURN")[1]
    for impossible in ("invade", "air_campaign", "blockade", "strike"):
        assert impossible not in offered


def test_owning_ground_forces_puts_invade_on_the_list():
    world = make_world(forces=(make_force("CU", "ground", region="r1"),))
    assert "invade" in rules.legal_action_types(world, "CU")
    assert "air_campaign" not in rules.legal_action_types(world, "CU")


def test_supply_is_offered_only_to_an_actor_that_can_afford_it():
    rich = make_world(actors={"RU": make_actor("RU", fuel_days=500.0), "CU": make_actor("CU")})
    poor = make_world(actors={"RU": make_actor("RU", fuel_days=5.0), "CU": make_actor("CU")})
    assert "supply" in rules.legal_action_types(rich, "RU")
    assert "supply" not in rules.legal_action_types(poor, "RU")


def test_an_action_outside_the_offered_list_is_a_schema_violation():
    legal = ("hold", "statement")
    with pytest.raises(SchemaViolation, match="not available to you"):
        parse_declaration('{"actions":[{"type":"invade"}]}', "CU", legal)


# --- prompt content ---------------------------------------------------------


def test_the_prompt_carries_the_briefing_verbatim():
    seen: dict = {}
    _player(briefing="Hold the island. Never negotiate on sovereignty.").decide(
        make_world(), random.Random(1), call=_capture(seen)
    )
    assert "Never negotiate on sovereignty." in seen["prompt"]


def test_the_prompt_reports_last_turns_resolutions():
    world = make_world()
    resolved, _ = rules.resolve(world, [Action(actor="US", type="sanction")], random.Random(1))
    seen: dict = {}
    _player().decide(resolved, random.Random(1), call=_capture(seen))
    assert "WHAT HAPPENED LAST TURN" in seen["prompt"]
    assert "escalation" in seen["prompt"]


def test_the_schema_is_handed_to_the_backend():
    seen: dict = {}
    _player().decide(make_world(), random.Random(1), call=_capture(seen))
    assert seen["schema"]["properties"]["actions"]["maxItems"] == MAX_ACTIONS_PER_TURN


def test_exact_fuel_of_other_actors_is_banded_not_disclosed():
    world = make_world(
        actors={"US": make_actor("US", fuel_days=123.0), "CU": make_actor("CU")},
    )
    seen: dict = {}
    _player().decide(world, random.Random(1), call=_capture(seen))
    others = seen["prompt"].split("OTHER ACTORS")[1].split("FORCES YOU CAN SEE")[0]
    assert "123" not in others
    assert "sufficient" in others


# --- tolerating what models actually send -----------------------------------


def test_a_reasoning_block_before_the_answer_is_stripped():
    text = (
        "<think>Maybe I should invade. No, too costly. Let me answer "
        '{"actions":[{"type":"invade"}]} ... actually no.</think>'
        '{"actions":[{"type":"statement"}],"rationale":"r","assessment":"a"}'
    )
    actions, _, _ = parse_declaration(text, "CU", ("hold", "statement"))
    assert [a.type for a in actions] == ["statement"]


def test_a_fenced_code_block_is_accepted():
    text = '```json\n{"actions":[{"type":"hold"}],"rationale":"r","assessment":"a"}\n```'
    actions, _, _ = parse_declaration(text, "CU", ("hold",))
    assert [a.type for a in actions] == ["hold"]


def test_prose_around_the_json_is_tolerated():
    text = 'Here is my decision:\n{"actions":[{"type":"hold"}],"rationale":"r","assessment":"a"}\nThanks.'
    actions, _, _ = parse_declaration(text, "CU", ("hold",))
    assert [a.type for a in actions] == ["hold"]


def test_the_last_json_object_wins_when_a_model_sends_drafts():
    text = '{"actions":[{"type":"statement"}]}\nOn reflection:\n{"actions":[{"type":"hold"}]}'
    actions, _, _ = parse_declaration(text, "CU", ("hold", "statement"))
    assert [a.type for a in actions] == ["hold"]


def test_extract_json_returns_none_when_there_is_nothing_to_find():
    assert extract_json("no json here, sorry") is None


def test_a_non_integer_intensity_degrades_to_one_instead_of_crashing():
    actions, _, _ = parse_declaration(
        '{"actions":[{"type":"hold","intensity":"high"}]}', "CU", ("hold",)
    )
    assert actions[0].intensity == 1


def test_too_many_actions_is_a_schema_violation():
    many = ",".join(['{"type":"hold"}'] * (MAX_ACTIONS_PER_TURN + 1))
    with pytest.raises(SchemaViolation, match="at most"):
        parse_declaration(f'{{"actions":[{many}]}}', "CU", ("hold",))


def test_an_empty_action_array_is_a_schema_violation():
    with pytest.raises(SchemaViolation, match="non-empty"):
        parse_declaration('{"actions":[]}', "CU", ("hold",))


def test_a_json_array_at_the_top_level_is_a_schema_violation():
    with pytest.raises(SchemaViolation, match="expected a JSON object"):
        parse_declaration('[{"type":"hold"}]', "CU", ("hold",))


def test_the_region_of_an_action_survives_parsing():
    actions, _, _ = parse_declaration(
        '{"actions":[{"type":"strike","region":"r1","intensity":2}]}', "US", ("strike",)
    )
    assert actions[0].region == "r1"
    assert actions[0].intensity == 2


def test_an_unknown_region_is_left_for_the_resolver_to_reject():
    """Players are not the place to validate the map: the resolver already
    rejects an unknown region with a named reason, and the player learns from
    seeing that rejection next turn."""
    actions, _, _ = parse_declaration(
        '{"actions":[{"type":"strike","region":"atlantis"}]}', "US", ("strike",)
    )
    assert actions[0].region == "atlantis"


def test_the_region_is_normalised_to_none_when_the_model_sends_an_empty_string():
    actions, _, _ = parse_declaration(
        '{"actions":[{"type":"hold","region":""}]}', "CU", ("hold",)
    )
    assert actions[0].region is None


def test_forces_must_be_an_array():
    with pytest.raises(SchemaViolation, match="'forces' must be an array"):
        parse_declaration(
            '{"actions":[{"type":"hold","forces":"all of them"}]}', "CU", ("hold",)
        )


def test_a_region_identifier_appears_in_the_map_section():
    world = make_world(regions={"cu-havana": make_region("cu-havana", "CU", name="Havana")})
    seen: dict = {}
    _player().decide(world, random.Random(1), call=_capture(seen))
    assert "cu-havana" in seen["prompt"].split("MAP")[1]


def test_the_prompt_states_which_regions_each_offensive_action_can_reach():
    """Added after the first live run: a 32B model repeated an out-of-reach air
    campaign three turns running with the map in front of it."""
    world = make_world(
        regions={
            "target": make_region("target", "CU", adjacency=("sea-1",)),
            "far": make_region("far", "CU"),
            "sea-1": make_region(
                "sea-1", "", terrain="sea", population=0, adjacency=("target",)
            ),
        },
        forces=(make_force("US", "air", region="sea-1"),),
    )
    seen: dict = {}
    _player(actor_id="US", briefing="You are the US.").decide(
        world, random.Random(1), call=_capture(seen)
    )
    offered = seen["prompt"].split("ACTIONS AVAILABLE TO YOU THIS TURN")[1]
    assert "air_campaign can reach: sea-1, target" in offered
    assert "far" not in offered.split("air_campaign can reach:")[1].split("\n")[0]


def test_reach_says_nowhere_when_the_platform_is_isolated():
    world = make_world(
        regions={
            "island": make_region("island", "CU"),
            "sea-1": make_region("sea-1", "", terrain="sea", population=0),
        },
        forces=(make_force("US", "ground", region="sea-1"),),
    )
    assert rules.reachable_regions(world, "US", "invade") == ("sea-1",)
    assert rules.reachable_regions(world, "US", "air_campaign") == ()
