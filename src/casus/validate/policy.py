"""Who declares what when the validator plays a scenario by itself.

`holding` has every actor hold. `sample` picks uniformly among what `offer`
allows. `cover` makes sure every offered action type is declared: in cover turn
j, each actor takes the j-th type it is offered (offset by its position), so a
run of as many turns as the scenario has action types declares all of them.
"""

from __future__ import annotations

import random

from ..players import offered_actions
from ..scenario import Scenario
from ..state import Action, WorldState


def holding(scenario: Scenario, world: WorldState, rng: random.Random, turn: int = 0):
    if "hold" not in scenario.actions:
        return []
    return [Action(actor=a, type="hold") for a in sorted(scenario.actors)]


def _action(scenario, world, actor, action_type, offered, rng) -> Action:
    spec = scenario.actions[action_type]
    fields = spec.get("fields") or ()
    place = (
        rng.choice(tuple(offered[action_type] or world.places)) if "place" in fields else None
    )
    others = [a for a in sorted(scenario.actors) if a != actor]
    target = rng.choice(others) if "target" in fields and others else None
    own = [e.id for e in world.entities if e.owner == actor]
    entities = (rng.choice(own),) if "entities" in fields and own else ()
    lo, hi = spec.get("intensity", (1, 1))
    intensity = rng.randint(int(lo), int(hi)) if "intensity" in fields else 1
    return Action(actor, action_type, place, target, entities, intensity)


def sample(scenario: Scenario, world: WorldState, rng: random.Random, turn: int = 0):
    actions = []
    for actor in sorted(scenario.actors):
        offered = offered_actions(scenario, world, actor, random.Random(0))
        if offered:
            action_type = rng.choice(sorted(offered))
            actions.append(_action(scenario, world, actor, action_type, offered, rng))
    return actions


def cover(scenario: Scenario, world: WorldState, rng: random.Random, turn: int = 0):
    actions = []
    for index, actor in enumerate(sorted(scenario.actors)):
        offered = offered_actions(scenario, world, actor, random.Random(0))
        if offered:
            types = sorted(offered)
            action_type = types[(turn + index) % len(types)]
            actions.append(_action(scenario, world, actor, action_type, offered, rng))
    return actions
