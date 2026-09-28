import json

from casus.v1.state import (
    ACTION_TYPES,
    ESCALATION_RUNGS,
    RUNG_NAMES,
    Action,
    Resolution,
    WorldState,
)
from helpers import make_force, make_region, make_world


def test_world_state_round_trips_through_json(world):
    assert WorldState.from_json(world.to_json()) == world


def test_round_trip_survives_a_json_text_encode_decode(world):
    reloaded = WorldState.from_json(json.loads(json.dumps(world.to_json())))
    assert reloaded == world
    assert reloaded.digest() == world.digest()


def test_digest_is_independent_of_key_insertion_order():
    a = make_world(regions={"r1": make_region("r1", "DEF"), "r2": make_region("r2", "ATK")})
    b = make_world(regions={"r2": make_region("r2", "ATK"), "r1": make_region("r1", "DEF")})
    assert a.digest() == b.digest()


def test_digest_changes_when_a_number_changes(world):
    before = world.digest()
    touched = world.replace_forces(
        tuple(
            f if f.owner != "DEF" else make_force("DEF", "ground", region="r1", strength=49.0)
            for f in world.forces
        )
    )
    assert touched.digest() != before, "a digest that ignores strength is not a check"


def test_every_action_type_has_a_rung_and_every_rung_has_a_name():
    assert set(ESCALATION_RUNGS) == set(ACTION_TYPES)
    assert set(ESCALATION_RUNGS.values()) <= set(range(len(RUNG_NAMES)))
    assert len(RUNG_NAMES) == 8


def test_action_rung_comes_from_the_ladder_not_from_a_literal():
    for action_type in ACTION_TYPES:
        action = Action(actor="ATK", type=action_type)
        assert action.rung == ESCALATION_RUNGS[action_type]


def test_invade_is_the_top_rung_and_hold_is_the_bottom():
    assert ESCALATION_RUNGS["invade"] == len(RUNG_NAMES) - 1
    assert ESCALATION_RUNGS["hold"] == 0


def test_action_round_trips_through_json():
    a = Action(actor="ATK", type="invade", region="r1", forces=("ATK-ground-1",), intensity=3)
    assert Action.from_json(a.to_json()) == a


def test_resolution_round_trips_through_json():
    r = Resolution(kind="fuel_exhausted", actor="DEF", reason="no fuel", detail={"days": 0})
    assert Resolution.from_json(r.to_json()) == r


def test_forces_of_and_forces_in_filter_independently(world):
    assert {f.owner for f in world.forces_of("DEF")} == {"DEF"}
    assert {f.region for f in world.forces_in("sea-1")} == {"sea-1"}


def test_relation_defaults_to_zero_for_an_unknown_pair(world):
    assert world.relation("ATK", "DEF") == -60
    assert world.relation("CN", "RU") == 0


def test_regions_of_returns_only_the_owners_regions(world):
    assert {r.id for r in world.regions_of("DEF")} == {"r1"}
