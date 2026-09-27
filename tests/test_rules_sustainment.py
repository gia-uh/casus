import random

from casus import rules
from casus.state import Action
from helpers import make_actor, make_force, make_region, make_world


def _resolve(world, actions, seed=1):
    return rules.resolve(world, actions, random.Random(seed))


def test_zero_fuel_forces_every_force_to_garrison():
    world = make_world(
        actors={"US": make_actor("US"), "CU": make_actor("CU", fuel_days=0.5, fuel_inflow=0.0)},
        forces=(
            make_force("CU", "ground", region="r1", posture="offensive"),
            make_force("CU", "air", region="r1", posture="offensive", id="CU-air-1"),
        ),
    )
    out, res = _resolve(world, [Action(actor="CU", type="hold")])

    assert out.actors["CU"].fuel_days == 0.0
    assert all(f.posture == "garrison" for f in out.forces_of("CU"))
    exhausted = [r for r in res if r.kind == "fuel_exhausted"]
    assert exhausted and exhausted[0].actor == "CU"
    assert "2 force(s) forced to garrison" in exhausted[0].reason


def test_an_actor_with_fuel_keeps_the_posture_it_declared():
    world = make_world(
        actors={"US": make_actor("US"), "CU": make_actor("CU", fuel_days=500.0)},
        forces=(make_force("CU", "ground", region="r1"),),
    )
    out, res = _resolve(world, [Action(actor="CU", type="disperse")])
    assert [f.posture for f in out.forces_of("CU")] == ["dispersed"]
    assert not [r for r in res if r.kind == "fuel_exhausted"]


def test_an_air_campaign_costs_more_fuel_than_a_statement():
    world = make_world(
        actors={"US": make_actor("US", fuel_days=200.0), "CU": make_actor("CU")},
        regions={
            "r1": make_region("r1", "CU", adjacency=("sea-1",)),
            "sea-1": make_region("sea-1", "", terrain="sea", population=0, adjacency=("r1",)),
        },
        forces=(
            make_force("US", "air", region="sea-1", strength=40.0),
            make_force("CU", "ground", region="r1"),
        ),
    )
    quiet, _ = _resolve(world, [Action(actor="US", type="statement")])
    loud, _ = _resolve(world, [Action(actor="US", type="air_campaign", region="r1")])
    assert loud.actors["US"].fuel_days < quiet.actors["US"].fuel_days

    # Exactly the surcharge, and nothing for the posture change: sustainment runs
    # before movement on purpose, so the offensive posture only starts costing
    # extra from the following turn. That ordering is a modelling decision, and
    # this is the assertion that pins it.
    spent = quiet.actors["US"].fuel_days - loud.actors["US"].fuel_days
    assert abs(spent - rules.ACTION_FUEL_SURCHARGE["air_campaign"]) < 1e-9


def test_burn_scales_with_force_kind_using_the_published_rates():
    """Irregulars are nearly free to keep and air is expensive. The assertion
    binds to BURN_RATE rather than to a number typed twice."""

    def fuel_after(kind):
        world = make_world(
            actors={
                "US": make_actor("US"),
                "CU": make_actor("CU", fuel_days=100.0, fuel_inflow=0.0),
            },
            forces=(make_force("CU", kind, region="r1", strength=10.0),),
        )
        out, _ = _resolve(world, [Action(actor="CU", type="hold")])
        return out.actors["CU"].fuel_days

    air, irregular = fuel_after("air"), fuel_after("irregular")
    assert air < irregular
    expected_gap = (rules.BURN_RATE["air"] - rules.BURN_RATE["irregular"]) * 10.0
    assert abs((irregular - air) - expected_gap) < 1e-9


def test_inflow_offsets_consumption():
    world = make_world(
        actors={
            "US": make_actor("US"),
            "CU": make_actor("CU", fuel_days=100.0, fuel_inflow=50.0),
        },
        forces=(make_force("CU", "ground", region="r1", strength=10.0),),
    )
    out, _ = _resolve(world, [Action(actor="CU", type="hold")])
    assert out.actors["CU"].fuel_days > 100.0, "inflow larger than burn should net positive"


def test_supply_moves_fuel_between_actors():
    world = make_world(
        actors={
            "RU": make_actor("RU", fuel_days=200.0),
            "CU": make_actor("CU", fuel_days=20.0, fuel_inflow=0.0),
        },
        forces=(),
    )
    out, res = _resolve(world, [Action(actor="RU", type="supply", target_actor="CU")])
    assert out.actors["CU"].fuel_days > 20.0
    assert out.actors["RU"].fuel_days < 200.0
    delivered = [r for r in res if r.kind == "supply_delivered"]
    assert delivered and delivered[0].detail["to"] == "CU"
    assert delivered[0].detail["amount"] == rules.SUPPLY_TRANSFER


def test_supply_is_rejected_when_the_supplier_cannot_pay():
    world = make_world(
        actors={"RU": make_actor("RU", fuel_days=5.0), "CU": make_actor("CU")},
        forces=(),
    )
    attempted, res = _resolve(world, [Action(actor="RU", type="supply", target_actor="CU")])
    control, _ = _resolve(world, [Action(actor="RU", type="statement")])

    rejected = [r for r in res if r.kind == "action_rejected"]
    assert rejected and rejected[0].reason == "insufficient fuel to supply"
    # Compared against a turn where nothing was attempted, not against the state
    # before the turn: every actor still collects its inflow either way.
    assert attempted.actors["CU"].fuel_days == control.actors["CU"].fuel_days


# --- mobilisation -----------------------------------------------------------


def test_mobilizing_calls_up_reserves_and_draws_down_the_pool():
    world = make_world(
        actors={"US": make_actor("US", reserve_pool=100.0), "CU": make_actor("CU")},
        forces=(make_force("US", "ground", region="r1", strength=5.0),),
    )
    out, res = _resolve(world, [Action(actor="US", type="mobilize")])

    army = next(f for f in out.forces if f.owner == "US")
    assert army.strength == 5.0 + rules.REINFORCEMENT_PER_MOBILIZE
    assert out.actors["US"].reserve_pool == 100.0 - rules.REINFORCEMENT_PER_MOBILIZE
    assert any(r.kind == "mobilized" for r in res)


def test_higher_intensity_mobilizes_more():
    def called(intensity):
        world = make_world(
            actors={"US": make_actor("US", reserve_pool=100.0), "CU": make_actor("CU")},
            forces=(make_force("US", "ground", region="r1", strength=5.0),),
        )
        out, _ = _resolve(world, [Action(actor="US", type="mobilize", intensity=intensity)])
        return next(f.strength for f in out.forces if f.owner == "US")

    assert called(3) > called(1)


def test_mobilization_cannot_exceed_the_reserve_pool():
    world = make_world(
        actors={"US": make_actor("US", reserve_pool=3.0), "CU": make_actor("CU")},
        forces=(make_force("US", "ground", region="r1", strength=5.0),),
    )
    out, _ = _resolve(world, [Action(actor="US", type="mobilize", intensity=3)])
    assert next(f.strength for f in out.forces if f.owner == "US") == 8.0
    assert out.actors["US"].reserve_pool == 0.0


def test_an_exhausted_pool_reports_rather_than_conjuring_troops():
    world = make_world(
        actors={"US": make_actor("US", reserve_pool=0.0), "CU": make_actor("CU")},
        forces=(make_force("US", "ground", region="r1", strength=5.0),),
    )
    out, res = _resolve(world, [Action(actor="US", type="mobilize")])
    assert next(f.strength for f in out.forces if f.owner == "US") == 5.0
    assert any(r.kind == "reserves_exhausted" for r in res)


def test_reaching_an_invasion_sized_force_takes_many_turns_of_mobilisation():
    """CSIS puts an invasion of Cuba at 100,000 personnel taking months to
    assemble and visible long before it begins. At this rate that is a dozen
    consecutive turns of open mobilisation, which is the point of the rule."""
    needed = 100_000 / rules.TROOPS_PER_STRENGTH_POINT
    turns = needed / rules.REINFORCEMENT_PER_MOBILIZE
    assert turns >= 12
