"""The world as data, with no domain vocabulary."""

import json
import pathlib

from casus import state
from casus.state import Action, Actor, Entity, Event, Place, WorldState


def _world(**overrides) -> WorldState:
    base = dict(
        turn=1,
        actors={
            "ATK": Actor(id="ATK", name="Attacker", resources={"support": 60.0}),
            "DEF": Actor(id="DEF", name="Defender", resources={"support": 70.0}),
        },
        places={
            "r1": Place(
                id="r1",
                name="One",
                owner="DEF",
                adjacency=("r2",),
                attrs={"infra": 100.0, "lat": 23.1, "terrain": "urban"},
            ),
            "r2": Place(id="r2", name="Two", owner="ATK", adjacency=("r1",), attrs={}),
        },
        entities=(
            Entity(
                id="f1",
                owner="DEF",
                kind="ground",
                place="r1",
                attrs={"strength": 50.0, "posture": "garrison"},
            ),
        ),
        events=(Event(id="attacked", detail={"place": "r1"}),),
    )
    base.update(overrides)
    return WorldState(**base)


def test_the_state_module_names_no_domain_concept():
    """v1 had fuel_days, munitions, isr and five force kinds in the type. A
    generalised engine that still mentions them has not generalised."""
    source = pathlib.Path(state.__file__).read_text()
    for leaked in (
        "fuel",
        "munitions",
        "isr",
        "air_defense",
        "legitimacy",
        "escalation",
        "reserve_pool",
        "terrain",
        "posture",
        "rung",
    ):
        assert leaked not in source.lower(), f"state.py still knows about {leaked}"


def test_world_state_round_trips_through_json():
    world = _world()
    assert WorldState.from_json(world.to_json()) == world


def test_round_trip_survives_a_json_text_encode_decode():
    world = _world()
    reloaded = WorldState.from_json(json.loads(json.dumps(world.to_json())))
    assert reloaded == world
    assert reloaded.digest() == world.digest()


def test_digest_is_independent_of_key_insertion_order():
    a = _world()
    b = _world(places=dict(reversed(list(_world().places.items()))))
    assert a.digest() == b.digest()


def test_digest_changes_when_a_number_changes():
    world = _world()
    touched = _world(
        actors={
            **world.actors,
            "DEF": Actor(id="DEF", name="Defender", resources={"support": 69.0}),
        }
    )
    assert touched.digest() != world.digest(), "a digest that ignores a resource is not a check"


def test_an_actor_with_an_arbitrary_resource_name_round_trips():
    world = _world(actors={"X": Actor(id="X", name="X", resources={"grain_stock": 12.5})})
    assert WorldState.from_json(world.to_json()).actors["X"].resources == {"grain_stock": 12.5}


def test_a_string_attribute_round_trips_and_moves_the_digest():
    world = _world()
    assert WorldState.from_json(world.to_json()).entities[0].attrs["posture"] == "garrison"
    hardened = _world(
        entities=(
            Entity(
                id="f1",
                owner="DEF",
                kind="ground",
                place="r1",
                attrs={"strength": 50.0, "posture": "hardened"},
            ),
        )
    )
    assert hardened.digest() != world.digest()


def test_action_round_trips_through_json():
    a = Action(
        actor="ATK", type="invade", place="r1", target="DEF", entities=("f1",), intensity=3
    )
    assert Action.from_json(a.to_json()) == a


def test_entity_order_is_part_of_the_state():
    """Spawned entities append. Order decides which one a rule finds first, so
    it must survive a round trip."""
    two = (
        Entity(id="b", owner="DEF", kind="ground", place="r1", attrs={}),
        Entity(id="a", owner="DEF", kind="ground", place="r1", attrs={}),
    )
    world = _world(entities=two)
    assert [e.id for e in WorldState.from_json(world.to_json()).entities] == ["b", "a"]
