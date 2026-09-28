"""The design rests on `rules.py` being pure, so that claim gets its own tests."""

import pathlib
import random

from casus.v1 import rules
from casus.v1.state import Action
from helpers import make_actor, make_force, make_world

FORBIDDEN_IN_RULES = (
    "httpx",
    "casus.llm",
    "from .llm",
    "import requests",
    "open(",
    "pathlib",
    "subprocess",
    "urllib",
)


def test_rules_module_performs_no_io():
    source = pathlib.Path(rules.__file__).read_text()
    for forbidden in FORBIDDEN_IN_RULES:
        assert forbidden not in source, f"rules.py must stay pure: found {forbidden!r}"


def test_rules_imports_nothing_that_talks_to_a_model():
    imported = {
        name
        for name in dir(rules)
        if not name.startswith("_") and hasattr(getattr(rules, name), "__module__")
    }
    modules = {getattr(rules, n).__module__ for n in imported}
    assert not any("llm" in m for m in modules), modules


def test_resolve_is_deterministic_for_a_given_seed():
    world = make_world(forces=(make_force("DEF", "ground", region="r1"),))
    actions = [Action(actor="ATK", type="statement")]
    first, _ = rules.resolve(world, actions, random.Random(7))
    second, _ = rules.resolve(world, actions, random.Random(7))
    assert first.digest() == second.digest()


def test_resolve_differs_across_seeds_when_combat_happens():
    """If two seeds gave the same answer, the jitter would not be doing anything
    and the spread we report to the class would be fake."""
    world = make_world(
        forces=(
            make_force("ATK", "ground", region="r1", strength=100.0, posture="offensive"),
            make_force("DEF", "ground", region="r1", strength=50.0, posture="defensive"),
        )
    )
    actions = [Action(actor="ATK", type="invade", region="r1")]
    a, _ = rules.resolve(world, actions, random.Random(1))
    b, _ = rules.resolve(world, actions, random.Random(999))
    assert a.digest() != b.digest()


def test_resolve_does_not_mutate_the_state_it_was_given():
    world = make_world(
        forces=(
            make_force("ATK", "ground", region="r1", strength=100.0, posture="offensive"),
            make_force("DEF", "ground", region="r1", strength=50.0),
        )
    )
    before = world.digest()
    rules.resolve(world, [Action(actor="ATK", type="invade", region="r1")], random.Random(3))
    assert world.digest() == before


def test_resolve_advances_the_turn_counter():
    world = make_world(turn=4)
    out, _ = rules.resolve(world, [], random.Random(1))
    assert out.turn == 5


def test_every_actor_keeps_its_identity_across_a_turn():
    world = make_world(actors={"ATK": make_actor("ATK"), "DEF": make_actor("DEF")})
    out, _ = rules.resolve(world, [], random.Random(1))
    assert set(out.actors) == set(world.actors)
