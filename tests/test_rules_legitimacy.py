import random

from casus import rules
from casus.state import Action
from helpers import make_actor, make_force, make_region, make_world


def _struck_world(**region_overrides):
    base = dict(terrain="urban", population=1_200_000, adjacency=("sea-1",))
    base.update(region_overrides)
    return make_world(
        actors={"US": make_actor("US", fuel_days=500.0), "CU": make_actor("CU")},
        regions={
            "cu-havana": make_region("cu-havana", "CU", **base),
            "sea-1": make_region(
                "sea-1", "", terrain="sea", population=0, adjacency=("cu-havana",)
            ),
        },
        forces=(make_force("US", "air", region="sea-1", strength=60.0),),
    )


def _strike(world, seed=4):
    return rules.resolve(
        world,
        [Action(actor="US", type="air_campaign", region="cu-havana", intensity=2)],
        random.Random(seed),
    )


def test_civilian_distress_costs_the_attacker_legitimacy_and_the_defender_support():
    world = _struck_world(infrastructure=20.0, civilian_distress=70.0)
    out, _ = _strike(world)

    assert out.actors["US"].intl_legitimacy < world.actors["US"].intl_legitimacy
    assert out.actors["CU"].domestic_support < world.actors["CU"].domestic_support


def test_the_two_costs_run_on_different_curves():
    """The same suffering is a liability for both sides, at different rates. That
    asymmetry is what makes a pressure campaign a race rather than a siege."""
    assert rules.LEGITIMACY_COST_PER_DISTRESS != rules.SUPPORT_COST_PER_DISTRESS


def test_distress_rises_with_damaged_infrastructure():
    intact, _ = _strike(_struck_world(infrastructure=100.0))
    wrecked, _ = _strike(_struck_world(infrastructure=30.0))
    assert (
        wrecked.regions["cu-havana"].civilian_distress
        > intact.regions["cu-havana"].civilian_distress
    )


def test_distress_accumulates_turn_on_turn_under_a_sustained_campaign():
    state = _struck_world(infrastructure=60.0)
    readings = []
    for _ in range(3):
        state, _ = _strike(state)
        readings.append(state.regions["cu-havana"].civilian_distress)
    assert readings == sorted(readings)
    assert readings[-1] > readings[0]


def test_distress_is_capped_at_one_hundred():
    state = _struck_world(infrastructure=0.0, civilian_distress=95.0)
    for _ in range(5):
        state, _ = _strike(state)
    assert state.regions["cu-havana"].civilian_distress == 100.0


def test_losing_all_fuel_raises_civilian_distress_on_its_own():
    """An energy blockade hurts civilians with nobody firing a shot. This is the
    mechanism behind the pressure-campaign branch."""
    world = make_world(
        actors={
            "US": make_actor("US"),
            "CU": make_actor("CU", fuel_days=0.2, fuel_inflow=0.0),
        },
        regions={"cu-havana": make_region("cu-havana", "CU", population=1_200_000)},
        forces=(make_force("CU", "ground", region="cu-havana", strength=40.0),),
    )
    out, resolutions = rules.resolve(world, [Action(actor="CU", type="hold")], random.Random(1))
    assert any(r.kind == "fuel_exhausted" for r in resolutions)
    assert out.regions["cu-havana"].civilian_distress >= rules.DISTRESS_FROM_FUEL_EXHAUSTION


def test_a_legitimacy_cost_is_reported_with_its_size():
    world = _struck_world(infrastructure=20.0, civilian_distress=70.0)
    _, resolutions = _strike(world)
    cost = next(r for r in resolutions if r.kind == "legitimacy_cost")
    assert cost.actor == "US"
    assert cost.detail["cost"] > 0
    assert cost.detail["distress"] > 70.0


def test_an_action_below_the_harm_rung_costs_no_legitimacy():
    world = _struck_world(infrastructure=20.0, civilian_distress=70.0)
    out, resolutions = rules.resolve(
        world, [Action(actor="US", type="sanction")], random.Random(1)
    )
    assert not [r for r in resolutions if r.kind == "legitimacy_cost"]
    assert out.actors["US"].intl_legitimacy == world.actors["US"].intl_legitimacy
    assert rules.ESCALATION_RUNGS["sanction"] < rules.HARM_RUNG


def test_striking_an_empty_sea_zone_costs_no_legitimacy():
    """A model that games the escalation chart by bombing open water should not
    also be punished for civilian harm it did not cause. This came out of a live
    run where exactly that happened."""
    world = _struck_world()
    out, resolutions = rules.resolve(
        world,
        [Action(actor="US", type="air_campaign", region="sea-1", intensity=3)],
        random.Random(1),
    )
    assert not [r for r in resolutions if r.kind == "legitimacy_cost"]
    assert out.actors["US"].intl_legitimacy == world.actors["US"].intl_legitimacy


def test_legitimacy_and_support_stay_within_bounds():
    state = _struck_world(infrastructure=0.0, civilian_distress=100.0)
    for _ in range(20):
        state, _ = _strike(state)
    assert 0.0 <= state.actors["US"].intl_legitimacy <= 100.0
    assert 0.0 <= state.actors["CU"].domestic_support <= 100.0
