"""The resolver: five phases, in order, atomically."""

import random
import types

import pytest

from casus import resolver
from casus.resolver import resolve
from casus.ruleset import RuleSet, rule
from casus.state import Action, Actor, Place, WorldState


def _state() -> WorldState:
    return WorldState(
        turn=1,
        actors={
            "ATK": Actor(id="ATK", name="Attacker", resources={"support": 50.0}),
            "DEF": Actor(id="DEF", name="Defender", resources={"support": 60.0}),
        },
        places={
            "capital": Place(
                id="capital", name="Capital", owner="DEF", adjacency=(), attrs={"infra": 80.0}
            )
        },
        entities=(),
    )


def _wrap(fn):
    """A fresh function object, so a decorator attribute never lands on a shared one."""
    return lambda *args: fn(*args)


def _module(rules):
    """Build a rules module from (phase, fn) or (phase, on, fn) tuples, in order."""
    module = types.ModuleType("scenario_rules")
    for index, spec in enumerate(rules):
        phase, on, fn = spec if len(spec) == 3 else (spec[0], None, spec[1])
        name = getattr(fn, "__name__", "<lambda>")
        if name == "<lambda>":
            name = f"rule_{index}"
        wrapped = _wrap(fn)
        wrapped.__name__ = name
        setattr(module, name, rule(phase=phase, on=on)(wrapped))
    return module


def _declared(*types_, **extra):
    return {t: {"fields": ["place", "intensity"], "intensity": [1, 3], **extra} for t in types_}


def _run(rules, actions=(), declared=None, seed=1, state=None):
    return resolve(
        state or _state(),
        list(actions),
        RuleSet.from_module(_module(rules)),
        random.Random(seed),
        declared or {},
    )


def test_phases_run_in_the_declared_order_whatever_order_the_rules_were_written_in():
    seen = []
    _run(
        [
            ("consequences", lambda s: seen.append("c")),
            ("legality", lambda s: seen.append("l")),
            ("contest", lambda s: seen.append("t")),
        ]
    )
    assert seen == ["l", "t", "c"]


def test_a_rule_cannot_see_an_event_from_a_later_phase():
    answers = {}
    _run(
        [
            ("upkeep", lambda s: answers.__setitem__("early", s.happened("boom"))),
            ("contest", lambda s: s.emit("boom")),
            ("consequences", lambda s: answers.__setitem__("late", s.happened("boom"))),
        ]
    )
    assert answers["early"] is False, "visibility must not depend on rule order"
    assert answers["late"] is True


def test_a_rule_with_on_runs_once_per_matching_action():
    hits = []
    _run(
        [("contest", "strike", lambda s, a: hits.append(a.place))],
        actions=[
            Action(actor="ATK", type="strike", place="capital"),
            Action(actor="DEF", type="hold"),
        ],
        declared={**_declared("strike"), "hold": {"fields": []}},
    )
    assert hits == ["capital"]


def test_a_rejected_action_is_public_and_gone_by_upkeep():
    counted = {}
    _, events, _ = _run(
        [
            ("legality", "invade", lambda s, a: s.reject("no ground forces available")),
            ("upkeep", lambda s: counted.__setitem__("n", len(s.actions))),
        ],
        actions=[Action(actor="ATK", type="invade", place="capital")],
        declared=_declared("invade"),
    )
    assert counted["n"] == 0
    (rejected,) = [e for e in events if e.id == "action_rejected"]
    assert rejected.detail["reason"] == "no ground forces available"
    assert rejected.detail["actor"] == "ATK"


def test_an_undeclared_action_type_is_rejected_by_the_engine():
    _, events, _ = _run([], actions=[Action(actor="ATK", type="teleport")], declared={})
    (rejected,) = events
    assert rejected.id == "action_rejected"
    assert "teleport" in rejected.detail["reason"]


def test_an_action_on_a_place_that_does_not_exist_is_rejected_by_the_engine():
    _, events, _ = _run(
        [],
        actions=[Action(actor="ATK", type="strike", place="atlantis")],
        declared=_declared("strike"),
    )
    (rejected,) = events
    assert "atlantis" in rejected.detail["reason"]


def test_a_rule_that_raises_abandons_the_turn_without_half_applying_it():
    """A half-applied turn on disk is worse than a failed run, because it
    replays as a plausible state nobody produced."""

    def explodes(s):
        s.add(s.actor("ATK").support, -5.0)
        raise KeyError("no such place: atlantis")

    before = _state()
    with pytest.raises(resolver.RuleFailed) as excinfo:
        _run([("contest", explodes)], state=before)
    assert "explodes" in str(excinfo.value)
    assert "atlantis" in str(excinfo.value)
    assert before.digest() == _state().digest(), "the input state is untouched"


def _jitter(s):
    s.add(s.place("capital").infra, -s.rng.uniform(0, 5))
    s.emit("hit", place="capital")


def test_the_same_turn_twice_gives_the_same_state_and_ledger():
    a = _run([("contest", _jitter)], seed=7)
    b = _run([("contest", _jitter)], seed=7)
    assert a[0].digest() == b[0].digest()
    assert a[2] == b[2]


def test_the_arrival_order_of_actions_does_not_matter():
    seen = []
    declared = _declared("strike")
    one = Action(actor="ATK", type="strike", place="capital")
    two = Action(actor="DEF", type="strike", place="capital")
    _run([("contest", "strike", lambda s, a: seen.append(a.actor))], [one, two], declared)
    _run([("contest", "strike", lambda s, a: seen.append(a.actor))], [two, one], declared)
    assert seen == ["ATK", "DEF", "ATK", "DEF"]


def test_intensity_is_clamped_to_the_declared_bounds_before_any_rule_sees_it():
    seen = []
    _run(
        [("contest", "strike", lambda s, a: seen.append(a.intensity))],
        [Action(actor="ATK", type="strike", place="capital", intensity=9)],
        _declared("strike"),
    )
    assert seen == [3]


def test_a_place_on_an_action_that_takes_none_is_dropped():
    seen = []
    _run(
        [("contest", "statement", lambda s, a: seen.append(a.place))],
        [Action(actor="ATK", type="statement", place="global")],
        {"statement": {"fields": []}},
    )
    assert seen == [None]


def test_the_turn_advances_and_the_events_travel_with_the_state():
    world, events, ledger = _run([("contest", _jitter)])
    assert world.turn == 2
    assert [e.id for e in world.events] == ["hit"] == [e.id for e in events]
    assert ledger and ledger[0].rule == "_jitter"
