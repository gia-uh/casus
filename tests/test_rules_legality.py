import random

from casus import rules
from casus.state import Action
from helpers import make_actor, make_force, make_region, make_world


def _resolve(world, actions, seed=1):
    return rules.resolve(world, actions, random.Random(seed))


def _rejections(res):
    return [r for r in res if r.kind == "action_rejected"]


def test_invading_without_ground_forces_is_rejected_with_a_reason():
    world = make_world(
        regions={"cu-havana": make_region("cu-havana", "CU")},
        forces=(make_force("US", "air", region="cu-havana"),),
    )
    out, res = _resolve(world, [Action(actor="US", type="invade", region="cu-havana")])

    rejected = _rejections(res)
    assert rejected and rejected[0].reason == "no ground forces available"
    assert out.regions["cu-havana"].owner == "CU"
    assert out.regions["cu-havana"].infrastructure == 100.0, "a rejected action does no damage"


def test_a_blockade_without_a_navy_is_rejected():
    world = make_world(forces=(make_force("CU", "ground", region="r1"),))
    _, res = _resolve(world, [Action(actor="CU", type="blockade", region="sea-1")])
    assert _rejections(res)[0].reason == "no naval forces available"


def test_an_air_campaign_needs_air_not_merely_naval():
    world = make_world(forces=(make_force("US", "naval", region="sea-1"),))
    _, res = _resolve(world, [Action(actor="US", type="air_campaign", region="r1")])
    assert _rejections(res)[0].reason == "no air forces available"


def test_a_strike_accepts_either_air_or_naval_platforms():
    world = make_world(
        regions={
            "r1": make_region("r1", "CU", adjacency=("sea-1",)),
            "sea-1": make_region("sea-1", "", terrain="sea", population=0, adjacency=("r1",)),
        },
        forces=(make_force("US", "naval", region="sea-1"),),
    )
    _, res = _resolve(world, [Action(actor="US", type="strike", region="r1")])
    assert not _rejections(res)


def test_forces_out_of_reach_are_rejected_even_when_the_right_kind_exists():
    world = make_world(
        regions={
            "r1": make_region("r1", "CU"),
            "far-away": make_region("far-away", "US"),
            "sea-1": make_region("sea-1", "", terrain="sea", population=0),
        },
        forces=(make_force("US", "ground", region="far-away"),),
    )
    _, res = _resolve(world, [Action(actor="US", type="invade", region="r1")])
    assert _rejections(res)[0].reason == "no invade platforms within reach of 'r1'"


def test_adjacency_puts_a_region_within_reach():
    world = make_world(
        regions={
            "r1": make_region("r1", "CU", adjacency=("beachhead",)),
            "beachhead": make_region("beachhead", "US", adjacency=("r1",)),
            "sea-1": make_region("sea-1", "", terrain="sea", population=0),
        },
        forces=(make_force("US", "ground", region="beachhead"),),
    )
    _, res = _resolve(world, [Action(actor="US", type="invade", region="r1")])
    assert not _rejections(res)


def test_an_unknown_region_is_rejected_by_name():
    world = make_world()
    _, res = _resolve(world, [Action(actor="US", type="strike", region="atlantis")])
    assert _rejections(res)[0].reason == "unknown region 'atlantis'"


def test_an_unknown_actor_is_rejected_by_name():
    world = make_world()
    _, res = _resolve(world, [Action(actor="ZZ", type="statement")])
    assert _rejections(res)[0].reason == "unknown actor 'ZZ'"


def test_an_unknown_action_type_is_rejected_rather_than_crashing():
    world = make_world()
    _, res = _resolve(world, [Action(actor="US", type="nuke_the_moon")])
    assert _rejections(res)[0].reason == "unknown action type 'nuke_the_moon'"


def test_commanding_another_actors_force_is_rejected():
    world = make_world(forces=(make_force("CU", "ground", region="r1", id="CU-ground-1"),))
    _, res = _resolve(
        world, [Action(actor="US", type="deploy", region="r1", forces=("CU-ground-1",))]
    )
    assert _rejections(res)[0].reason == "force 'CU-ground-1' belongs to CU"


def test_deploying_an_unknown_force_is_rejected_by_id():
    world = make_world()
    _, res = _resolve(
        world, [Action(actor="US", type="deploy", region="r1", forces=("ghost",))]
    )
    assert _rejections(res)[0].reason == "unknown force 'ghost'"


def test_supply_without_a_target_is_rejected():
    world = make_world(actors={"RU": make_actor("RU", fuel_days=500.0), "CU": make_actor("CU")})
    _, res = _resolve(world, [Action(actor="RU", type="supply")])
    assert _rejections(res)[0].reason == "supply needs a target actor"


def test_a_rejection_carries_the_whole_action_so_the_player_can_learn_from_it():
    world = make_world()
    action = Action(actor="US", type="invade", region="r1", intensity=3)
    _, res = _resolve(world, [action])
    assert _rejections(res)[0].detail["action"] == action.to_json()


def test_a_legal_action_alongside_an_illegal_one_still_happens():
    world = make_world(
        regions={
            "r1": make_region("r1", "CU", adjacency=("sea-1",)),
            "sea-1": make_region("sea-1", "", terrain="sea", population=0, adjacency=("r1",)),
        },
        forces=(make_force("US", "naval", region="sea-1"),),
    )
    out, res = _resolve(
        world,
        [
            Action(actor="US", type="invade", region="r1"),  # no ground forces
            Action(actor="US", type="strike", region="r1"),  # legal
        ],
    )
    assert len(_rejections(res)) == 1
    assert out.regions["r1"].infrastructure < 100.0, "the legal strike should have landed"
