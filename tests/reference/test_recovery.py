"""The ratchet repair: reconstruction, distress easing, support recovering.

v1 had none of the three, so civilian distress could only rise and domestic
support could only fall. The rates are design choices with no published
source; they live as constants in the reference ruleset.
"""

import dataclasses
import random

from reference_rules import MODULE, REFERENCE

from casus.resolver import resolve
from casus.state import Action


def _world(infra=50.0, distress=60.0, support=40.0):
    world = REFERENCE.initial_state()
    places = {
        k: dataclasses.replace(p, attrs={**p.attrs, "infrastructure": infra,
                                         "civilian_distress": distress})
        for k, p in world.places.items()
    }  # fmt: skip
    actors = {
        k: dataclasses.replace(a, resources={**a.resources, "domestic_support": support})
        for k, a in world.actors.items()
    }
    return dataclasses.replace(world, places=places, actors=actors)


def _turn(world, actions=()):
    new, _, _ = resolve(world, list(actions), REFERENCE.ruleset, random.Random(1),
                        REFERENCE.actions, REFERENCE.resource_bounds(),
                        REFERENCE.attribute_bounds())  # fmt: skip
    return new


def _hold(world):
    return [Action(actor=a, type="hold") for a in world.actors]


def test_an_unattacked_place_rebuilds_toward_full_infrastructure():
    world = _world(infra=50.0)
    after = _turn(world, _hold(world))
    before = world.places["g-capital"].attrs["infrastructure"]
    rebuilt = after.places["g-capital"].attrs["infrastructure"]
    assert rebuilt == before + (100.0 - before) * MODULE.RECONSTRUCTION_RATE


def test_a_place_attacked_this_turn_does_not_rebuild_or_ease():
    from casus.players import offered_actions

    world = _world(infra=50.0, distress=60.0)
    offered = offered_actions(REFERENCE, world, "BLUE", random.Random(0))
    target = next(p for p in offered["air_campaign"] if world.places[p].attrs["population"])
    strike = Action(actor="BLUE", type="air_campaign", place=target, intensity=1)
    after = _turn(world, [strike, Action(actor="GREEN", type="hold")])
    assert after.places[target].attrs["infrastructure"] < 50.0
    assert after.places[target].attrs["civilian_distress"] >= 60.0


def test_distress_does_not_ease_while_the_owner_is_out_of_fuel():
    world = _world(infra=100.0, distress=60.0)
    green = world.actors["GREEN"]
    dry = dataclasses.replace(
        green, resources={**green.resources, "fuel_days": 0.1, "fuel_inflow": 0.0}
    )
    world = dataclasses.replace(world, actors={**world.actors, "GREEN": dry})
    after = _turn(world, _hold(world))
    assert after.places["g-capital"].attrs["civilian_distress"] >= 60.0


def test_distress_eases_in_a_quiet_place_once_the_damage_is_repaired():
    world = _world(infra=100.0, distress=60.0)
    after = _turn(world, _hold(world))
    assert after.places["g-capital"].attrs["civilian_distress"] == 60.0 * (
        1 - MODULE.DISTRESS_RELIEF_RATE
    )


def test_support_recovers_toward_its_baseline_when_nothing_hurts():
    world = _world(infra=100.0, distress=0.0, support=40.0)
    after = _turn(world, _hold(world))
    baseline = world.actors["GREEN"].resources["support_baseline"]
    assert baseline > 40.0
    assert (
        after.actors["GREEN"].resources["domestic_support"]
        == 40.0 + (baseline - 40.0) * MODULE.SUPPORT_RECOVERY_RATE
    )


def test_with_the_rates_at_zero_the_ruleset_is_v1_again():
    """The acceptance test replays v1's recording on this: the repair must be
    something the rates switch off entirely."""
    source = REFERENCE.rules_source
    for name in ("RECONSTRUCTION_RATE", "DISTRESS_RELIEF_RATE", "SUPPORT_RECOVERY_RATE"):
        assert f"\n{name} = " in source
