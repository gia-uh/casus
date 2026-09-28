import random

from casus.v1 import rules
from casus.v1.state import Action
from helpers import make_force, make_region, make_world


def _resolve(world, actions, seed=3):
    return rules.resolve(world, actions, random.Random(seed))


def _force(out, owner):
    return next(f for f in out.forces if f.owner == owner)


def _contested_world(**region_overrides):
    return make_world(
        regions={"r1": make_region("r1", "DEF", **region_overrides)},
        forces=(
            make_force("ATK", "ground", region="r1", strength=100.0, posture="offensive"),
            make_force("DEF", "ground", region="r1", strength=50.0, posture="defensive"),
        ),
    )


def test_lanchester_exchange_favours_the_larger_force_quadratically():
    out, _ = _resolve(_contested_world(), [Action(actor="ATK", type="invade", region="r1")])
    attacker, defender = _force(out, "ATK"), _force(out, "DEF")
    assert defender.strength < attacker.strength / 2
    assert attacker.strength < 100.0, "the attacker pays too; a free win is not a model"


def test_both_sides_lose_something_and_the_exchange_is_reported():
    _, res = _resolve(_contested_world(), [Action(actor="ATK", type="invade", region="r1")])
    exchange = next(r for r in res if r.kind == "exchange")
    assert exchange.detail["attacker_losses"] > 0
    assert exchange.detail["defender_losses"] > exchange.detail["attacker_losses"]
    assert exchange.region == "r1"


def test_urban_terrain_protects_the_defender():
    coastal, _ = _resolve(
        _contested_world(terrain="coastal"), [Action(actor="ATK", type="invade", region="r1")]
    )
    urban, _ = _resolve(
        _contested_world(terrain="urban"), [Action(actor="ATK", type="invade", region="r1")]
    )
    assert _force(urban, "DEF").strength > _force(coastal, "DEF").strength
    ratio = rules.TERRAIN_DEFENSE["urban"] / rules.TERRAIN_DEFENSE["coastal"]
    assert ratio > 1.0


def test_an_irregular_defender_in_a_city_is_harder_to_grind_down_than_a_regular_one():
    def survive(kind):
        world = make_world(
            regions={"r1": make_region("r1", "DEF", terrain="urban")},
            forces=(
                make_force("ATK", "ground", region="r1", strength=100.0, posture="offensive"),
                make_force("DEF", kind, region="r1", strength=50.0, posture="defensive"),
            ),
        )
        out, _ = _resolve(world, [Action(actor="ATK", type="invade", region="r1")])
        return _force(out, "DEF").strength

    assert survive("irregular") > survive("ground")
    assert rules.IRREGULAR_TERRAIN_BONUS > 1.0


def test_hardening_reduces_incoming_damage_more_than_defending_does():
    def survive(posture):
        world = make_world(
            regions={"r1": make_region("r1", "DEF")},
            forces=(
                make_force("ATK", "ground", region="r1", strength=100.0, posture="offensive"),
                make_force("DEF", "ground", region="r1", strength=50.0, posture=posture),
            ),
        )
        out, _ = _resolve(world, [Action(actor="ATK", type="invade", region="r1")])
        return _force(out, "DEF").strength

    assert survive("hardened") > survive("defensive") > survive("garrison")
    assert (
        rules.POSTURE_DEFENSE["hardened"]
        > rules.POSTURE_DEFENSE["defensive"]
        > rules.POSTURE_DEFENSE["garrison"]
    )


def test_higher_intensity_inflicts_more_damage_on_the_defender():
    light, _ = _resolve(
        _contested_world(), [Action(actor="ATK", type="invade", region="r1", intensity=1)]
    )
    heavy, _ = _resolve(
        _contested_world(), [Action(actor="ATK", type="invade", region="r1", intensity=3)]
    )
    assert _force(heavy, "DEF").strength < _force(light, "DEF").strength


def test_intensity_is_clamped_so_a_model_cannot_ask_for_a_thousand():
    out, res = _resolve(
        _contested_world(), [Action(actor="ATK", type="invade", region="r1", intensity=1000)]
    )
    at_max, _ = _resolve(
        _contested_world(), [Action(actor="ATK", type="invade", region="r1", intensity=3)]
    )
    assert _force(out, "DEF").strength == _force(at_max, "DEF").strength
    assert "intensity 3" in next(r for r in res if r.kind == "exchange").reason


def test_a_force_is_never_reduced_below_zero():
    world = make_world(
        regions={"r1": make_region("r1", "DEF")},
        forces=(
            make_force("ATK", "ground", region="r1", strength=10_000.0, posture="offensive"),
            make_force("DEF", "ground", region="r1", strength=1.0, posture="defensive"),
        ),
    )
    out, _ = _resolve(world, [Action(actor="ATK", type="invade", region="r1")])
    assert _force(out, "DEF").strength == 0.0


def test_an_undefended_region_is_reported_as_unopposed_and_takes_damage():
    world = make_world(
        regions={
            "r1": make_region("r1", "DEF", adjacency=("sea-1",)),
            "sea-1": make_region("sea-1", "", terrain="sea", population=0, adjacency=("r1",)),
        },
        forces=(make_force("ATK", "air", region="sea-1", strength=40.0),),
    )
    out, res = _resolve(world, [Action(actor="ATK", type="air_campaign", region="r1")])
    assert any(r.kind == "unopposed" for r in res)
    assert out.regions["r1"].infrastructure < 100.0


def test_an_air_campaign_damages_infrastructure_more_than_a_single_strike():
    def infra(action_type):
        world = make_world(
            regions={
                "r1": make_region("r1", "DEF", adjacency=("sea-1",)),
                "sea-1": make_region(
                    "sea-1", "", terrain="sea", population=0, adjacency=("r1",)
                ),
            },
            forces=(make_force("ATK", "air", region="sea-1", strength=40.0),),
        )
        out, _ = _resolve(world, [Action(actor="ATK", type=action_type, region="r1")])
        return out.regions["r1"].infrastructure

    assert infra("air_campaign") < infra("strike")


def test_resolution_order_does_not_depend_on_the_order_actions_arrive_in():
    """Two actors acting in the same turn must resolve the same way whichever
    order the engine happened to collect their declarations in."""
    a = [Action(actor="ATK", type="invade", region="r1"), Action(actor="DEF", type="harden")]
    forward, _ = _resolve(_contested_world(), a)
    backward, _ = _resolve(_contested_world(), list(reversed(a)))
    assert forward.digest() == backward.digest()
