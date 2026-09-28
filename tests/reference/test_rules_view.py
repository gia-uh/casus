"""The reference ruleset's player-side hooks: what an actor sees, and what it may
declare. Carried over from v1's player tests, where these lived beside the
prompt."""

import random

from reference_rules import rules

from helpers import make_actor, make_force, make_region, make_world


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


def test_no_forces_means_no_delivery_actions_on_the_list():
    offered = rules.legal_action_types(make_world(forces=()), "DEF")
    for impossible in ("invade", "air_campaign", "blockade", "strike"):
        assert impossible not in offered


def test_owning_ground_forces_puts_invade_on_the_list():
    world = make_world(forces=(make_force("DEF", "ground", region="r1"),))
    assert "invade" in rules.legal_action_types(world, "DEF")
    assert "air_campaign" not in rules.legal_action_types(world, "DEF")


def test_a_delivery_action_offers_only_the_places_it_can_reach():
    world = make_world(
        regions={
            "r1": make_region("r1", "DEF", adjacency=("sea-1",)),
            "sea-1": make_region("sea-1", "", terrain="sea", population=0, adjacency=("r1",)),
            "far": make_region("far", "DEF"),
        },
        forces=(make_force("ATK", "air", region="sea-1"),),
    )
    assert rules.reachable_regions(world, "ATK", "air_campaign") == ("r1", "sea-1")
