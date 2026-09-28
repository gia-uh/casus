"""The rule surface: views, refs, the sixteen calls, and the ledger."""

import math
import random

import pytest

from casus import proxy
from casus.proxy import State
from casus.state import Action, Actor, Entity, Place, WorldState


def _state(
    actors=None,
    places=None,
    entities=None,
    bounds=None,
    attr_bounds=None,
    actions=(),
    phase="contest",
) -> State:
    world = WorldState(
        turn=3,
        actors={
            a: Actor(id=a, name=a, resources=dict(res))
            for a, res in (
                actors or {"ATK": {"support": 50.0}, "DEF": {"support": 60.0}}
            ).items()
        },
        places={
            p: Place(
                id=p,
                name=p,
                owner=attrs.pop("owner", "DEF") if "owner" in attrs else "DEF",
                adjacency=(),
                attrs=dict(attrs),
            )
            for p, attrs in {
                k: dict(v) for k, v in (places or {"capital": {"infra": 62.0}}).items()
            }.items()
        },
        entities=tuple(
            Entity(
                id=e["id"],
                owner=e.get("owner", "DEF"),
                kind=e.get("kind", "ground"),
                place=e.get("place", "capital"),
                attrs=dict(e.get("attrs", {})),
            )
            for e in (entities or [])
        ),
    )
    s = State(
        world,
        rng=random.Random(1),
        resource_bounds=bounds or {},
        attribute_bounds=attr_bounds or {},
    )
    s.set_actions([proxy.ActionView.of(a, {}) for a in actions])
    return s


def test_a_ref_behaves_as_its_value_and_remembers_its_path():
    s = _state(places={"capital": {"infra": 62.0}})
    ref = s.place("capital").infra
    assert 100 - ref == 38.0
    assert ref < 70 and ref == 62.0
    assert ref.path == "place.capital.infra"


def test_a_string_ref_works_as_a_dict_key_and_in_membership():
    s = _state(places={"capital": {"terrain": "urban"}})
    terrain = s.place("capital").terrain
    assert {"urban": 1.5}.get(terrain) == 1.5
    assert terrain in ("urban", "rural")


def test_every_mutation_lands_in_the_ledger_with_its_rule():
    s = _state(places={"capital": {"infra": 62.0}})
    with s.attributing(rule="bombing", phase="contest"):
        s.add(s.place("capital").infra, -8.0)
    (entry,) = s.ledger
    assert entry.rule == "bombing"
    assert entry.ref == "place.capital.infra"
    assert (entry.before, entry.after) == (62.0, 54.0)
    assert (entry.turn, entry.phase) == (3, "contest")


def test_a_clamped_add_records_what_happened_not_what_was_asked():
    """The ledger has to reconstruct the final value by summation. If it records
    the requested delta rather than the applied one, it stops being a record."""
    s = _state(actors={"ATK": {"support": 3.0}}, bounds={"support": (0.0, 100.0)})
    with s.attributing(rule="attrition", phase="consequences"):
        s.add(s.actor("ATK").support, -10.0)
    (entry,) = s.ledger
    assert entry.after == 0.0
    assert entry.before - entry.after == 3.0, "records the applied delta"
    assert s.actor("ATK").support == 0.0


def test_a_mutation_that_changes_nothing_leaves_no_entry():
    s = _state(actors={"ATK": {"support": 0.0}}, bounds={"support": (0.0, 100.0)})
    with s.attributing(rule="drain", phase="consequences"):
        s.add(s.actor("ATK").support, -4.0)
    assert s.ledger == []


def test_offer_cannot_change_the_world():
    s = _state(places={"capital": {"infra": 62.0}}).read_only("offer")
    with pytest.raises(proxy.ReadOnly, match="offer"):
        s.add(s.place("capital").infra, -1.0)


def test_a_read_only_proxy_still_reads():
    s = _state(places={"capital": {"infra": 62.0}}).read_only("offer")
    assert s.place("capital").infra == 62.0


def test_a_view_changes_a_copy_and_leaves_no_trace():
    world = _state(entities=[{"id": "f1", "attrs": {"strength": 10.0}}])
    seen = world.scratch()
    seen.set(seen.entity("f1").strength, 13.0)
    assert seen.entity("f1").strength == 13.0
    assert world.entity("f1").strength == 10.0
    assert world.ledger == []


def test_set_writes_numbers_and_strings():
    s = _state(entities=[{"id": "f1", "attrs": {"posture": "garrison", "strength": 5.0}}])
    with s.attributing(rule="dig_in", phase="movement"):
        s.set(s.entity("f1").posture, "hardened")
        s.set(s.entity("f1").strength, 7.5)
    assert s.entity("f1").posture == "hardened"
    assert [(m.before, m.after) for m in s.ledger] == [("garrison", "hardened"), (5.0, 7.5)]


def test_set_respects_the_bounds():
    s = _state(actors={"ATK": {"support": 50.0}}, bounds={"support": (0.0, 100.0)})
    with s.attributing(rule="r", phase="upkeep"):
        s.set(s.actor("ATK").support, 140.0)
    assert s.actor("ATK").support == 100.0


def test_transfer_conserves_the_total_and_writes_two_entries():
    s = _state(actors={"RU": {"fuel": 40.0}, "CU": {"fuel": 5.0}})
    with s.attributing(rule="supply", phase="upkeep"):
        s.transfer(s.actor("RU").fuel, s.actor("CU").fuel, 10.0)
    assert (s.actor("RU").fuel, s.actor("CU").fuel) == (30.0, 15.0)
    assert [m.ref for m in s.ledger] == ["actor.RU.fuel", "actor.CU.fuel"]


def test_transfer_moves_only_what_the_source_has():
    s = _state(
        actors={"RU": {"fuel": 4.0}, "CU": {"fuel": 5.0}}, bounds={"fuel": (0.0, math.inf)}
    )
    with s.attributing(rule="supply", phase="upkeep"):
        s.transfer(s.actor("RU").fuel, s.actor("CU").fuel, 10.0)
    assert s.actor("RU").fuel + s.actor("CU").fuel == 9.0
    assert s.actor("RU").fuel == 0.0


def test_decay_moves_toward_the_target_and_never_past_it():
    s = _state(places={"capital": {"infra": 60.0}})
    with s.attributing(rule="rebuild", phase="consequences"):
        s.decay(s.place("capital").infra, toward=100.0, rate=0.25)
        assert s.place("capital").infra == 70.0
        s.decay(s.place("capital").infra, toward=100.0, rate=5.0)
    assert s.place("capital").infra == 100.0


def test_move_changes_where_an_entity_is():
    s = _state(places={"capital": {}, "coast": {}}, entities=[{"id": "f1"}])
    with s.attributing(rule="deploy", phase="movement"):
        s.move(s.entity("f1"), "coast")
    assert s.entity("f1").place == "coast"
    assert s.ledger[0].ref == "entity.f1.place"


def test_move_to_an_unknown_place_is_refused():
    s = _state(entities=[{"id": "f1"}])
    with pytest.raises(proxy.UnknownName, match="atlantis"):
        s.move(s.entity("f1"), "atlantis")


def test_spawn_appends_and_despawn_removes():
    s = _state(entities=[{"id": "f1"}])
    with s.attributing(rule="insurgency", phase="consequences"):
        s.spawn(id="f2", kind="irregular", owner="DEF", place="capital", strength=2.5)
        assert [e.id for e in s.entities] == ["f1", "f2"]
        assert s.entity("f2").strength == 2.5
        s.despawn(s.entity("f1"))
    assert [e.id for e in s.entities] == ["f2"]
    assert [m.ref for m in s.ledger] == ["entity.f2", "entity.f1"]


def test_spawning_a_duplicate_id_is_refused():
    s = _state(entities=[{"id": "f1"}])
    with pytest.raises(ValueError, match="f1"):
        s.spawn(id="f1", kind="ground", owner="DEF", place="capital")


def test_happened_sees_earlier_events_and_matches_on_detail():
    s = _state()
    with s.attributing(rule="bombing", phase="contest"):
        s.emit("attacked", place="capital", actor="ATK")
    with s.attributing(rule="rebuild", phase="consequences"):
        assert s.happened("attacked")
        assert s.happened("attacked", place="capital")
        assert not s.happened("attacked", place="coast")


def test_a_rule_does_not_see_its_own_events():
    s = _state()
    with s.attributing(rule="bombing", phase="contest"):
        s.emit("attacked", place="capital")
        assert not s.happened("attacked"), "only earlier rules and phases are visible"


def test_reject_outside_legality_is_refused():
    s = _state()
    with (
        s.attributing(rule="late", phase="contest"),
        pytest.raises(proxy.RuleError, match="legality"),
    ):
        s.reject("too late")


def test_reject_in_legality_marks_the_action_and_emits_a_public_event():
    invade = Action(actor="ATK", type="invade", place="capital")
    s = _state(actions=[invade])
    (action,) = s.actions
    with s.attributing(rule="needs_ground", phase="legality", action=action):
        s.reject("no ground forces available")
    assert s.rejected(action)
    (event,) = s.events
    assert event.id == "action_rejected"
    assert event.detail["actor"] == "ATK"
    assert event.detail["place"] == "capital"
    assert event.detail["reason"] == "no ground forces available"


def test_find_filters_by_kind_owner_and_place_in_order():
    s = _state(
        places={"capital": {}, "coast": {}},
        entities=[
            {"id": "a", "kind": "air", "owner": "ATK", "place": "coast"},
            {"id": "b", "kind": "ground", "owner": "DEF", "place": "capital"},
            {"id": "c", "kind": "ground", "owner": "DEF", "place": "coast"},
        ],
    )
    assert [e.id for e in s.find(kind="ground")] == ["b", "c"]
    assert [e.id for e in s.find(owner="DEF", place="coast")] == ["c"]


def test_actions_carry_their_declaration():
    s = _state()
    s.set_actions(
        [
            proxy.ActionView.of(
                Action(actor="ATK", type="strike", place="capital"), {"strike": {"rung": 5}}
            )
        ]
    )
    (strike,) = s.actions
    assert (strike.actor, strike.type, strike.place) == ("ATK", "strike", "capital")
    assert strike.declared["rung"] == 5


def test_rng_is_the_seeded_generator():
    a, b = _state(), _state()
    assert a.rng.uniform(0, 1) == b.rng.uniform(0, 1)


def test_an_unknown_name_says_what_was_asked_for():
    s = _state()
    with pytest.raises(proxy.UnknownName, match="place 'atlantis'"):
        s.place("atlantis")
    with pytest.raises(proxy.UnknownName, match="resource 'fuel'"):
        _ = s.actor("ATK").fuel


def test_freeze_returns_the_world_with_its_events():
    s = _state(places={"capital": {"infra": 62.0}})
    with s.attributing(rule="bombing", phase="contest"):
        s.add(s.place("capital").infra, -2.0)
        s.emit("attacked", place="capital")
    frozen = s.freeze()
    assert frozen.places["capital"].attrs["infra"] == 60.0
    assert [e.id for e in frozen.events] == ["attacked"]


def test_assigning_through_a_view_is_refused_at_run_time():
    """The static validator rejects this at load. This is the second line."""
    s = _state()
    with pytest.raises(proxy.RuleError, match="s.set"):
        s.place("capital").infra = 5
