"""Scenario invariants: can a two-way quantity actually move both ways?

On 2026-09-27 Cuban domestic support reached zero on turn six with every actor
holding, because nothing in the rules could raise it. That survived 196 tests
and two scored runs. This module turns it into a check.

A quantity the scenario declares `monotone: false` must, somewhere across the
runs, both rise and fall. The runs are one in which every actor holds and
`random_runs` in which every actor picks uniformly among what `offer` gives it.
Holding alone would not answer the question: when everyone holds, nobody pushes
a variable back, so moving one way is the normal case. The random runs are there
to show whether the variable *can* go the other way.

Separately, in the holding run no such quantity may be driven to one of its
bounds and stay there to the end.
"""

from __future__ import annotations

import itertools
import random
from collections import defaultdict

from ..players import offered_actions
from ..resolver import RuleFailed, resolve
from ..scenario import Scenario
from ..state import Action, WorldState
from . import Finding

Samples = dict[tuple[str, str], list[float]]


def _two_way(scenario: Scenario) -> dict[str, tuple[float, float]]:
    """Quantities declared `monotone: false`, with their bounds."""
    out = {}
    for table, bounds in (
        (scenario.resources, scenario.resource_bounds()),
        (scenario.attributes, scenario.attribute_bounds()),
    ):
        for name, spec in table.items():
            if spec.get("monotone") is False:
                out[name] = bounds[name]
    return out


def _sample(world: WorldState, names: set[str], into: Samples) -> None:
    for actor in world.actors.values():
        for name in names & set(actor.resources):
            into[(f"actor {actor.id}", name)].append(float(actor.resources[name]))
    for place in world.places.values():
        for name in names & set(place.attrs):
            into[(f"place {place.id}", name)].append(float(place.attrs[name]))
    for entity in world.entities:
        for name in names & set(entity.attrs):
            into[(f"entity {entity.id}", name)].append(float(entity.attrs[name]))


def _choose(scenario: Scenario, world: WorldState, rng: random.Random) -> list[Action]:
    actions = []
    places = tuple(world.places)
    for actor in sorted(scenario.actors):
        offered = offered_actions(scenario, world, actor, random.Random(0))
        if not offered:
            continue
        action_type = rng.choice(sorted(offered))
        spec = scenario.actions[action_type]
        fields = spec.get("fields") or ()
        place = None
        if "place" in fields:
            place = rng.choice(tuple(offered[action_type] or places))
        others = [a for a in sorted(scenario.actors) if a != actor]
        target = rng.choice(others) if "target" in fields and others else None
        own = [e.id for e in world.entities if e.owner == actor]
        entities = (rng.choice(own),) if "entities" in fields and own else ()
        lo, hi = spec.get("intensity", (1, 1))
        intensity = rng.randint(int(lo), int(hi)) if "intensity" in fields else 1
        actions.append(Action(actor, action_type, place, target, entities, intensity))
    return actions


def _run(scenario: Scenario, turns: int, seed: int, policy, names: set[str]):
    rng = random.Random(seed)
    choices = random.Random(seed + 7919)
    world = scenario.initial_state()
    samples: Samples = defaultdict(list)
    _sample(world, names, samples)
    for _ in range(turns):
        actions = policy(scenario, world, choices)
        world, _, _ = resolve(
            world,
            actions,
            scenario.ruleset,
            rng,
            scenario.actions,
            scenario.resource_bounds(),
            scenario.attribute_bounds(),
        )
        _sample(world, names, samples)
    return samples


def _holding(scenario: Scenario, world: WorldState, rng: random.Random) -> list[Action]:
    if "hold" not in scenario.actions:
        return []
    return [Action(actor=a, type="hold") for a in sorted(scenario.actors)]


def check_invariants(
    scenario: Scenario, turns: int = 12, random_runs: int = 8, seed: int = 0
) -> list[Finding]:
    two_way = _two_way(scenario)
    if not two_way:
        return []
    names = set(two_way)
    try:
        holding = _run(scenario, turns, seed, _holding, names)
        runs = [holding] + [
            _run(scenario, turns, seed + 1 + i, _choose, names) for i in range(random_runs)
        ]
    except RuleFailed as exc:
        return [Finding("rule-error", str(exc), scenario.origin)]

    findings = []
    for name in sorted(names):
        rose = fell = False
        for samples in runs:
            for (_, quantity), values in samples.items():
                if quantity != name:
                    continue
                for before, after in itertools.pairwise(values):
                    rose |= after > before
                    fell |= after < before
        missing = [word for word, happened in (("rose", rose), ("fell", fell)) if not happened]
        if missing:
            findings.append(
                Finding(
                    "monotone-quantity",
                    f"'{name}' is declared monotone: false but never "
                    f"{' and never '.join(missing)} across {len(runs)} runs of {turns} turns "
                    "(one holding, the rest random); nothing in the rules can move it "
                    f"{'up' if not rose else 'down'}",
                    scenario.origin,
                )
            )

    for (holder, name), values in sorted(holding.items()):
        lo, hi = two_way[name]
        for bound in (lo, hi):
            pinned = len(values) >= 3 and values[0] != bound and values[-1] == values[-2] == bound
            if pinned:
                reached = next(i for i, v in enumerate(values) if v == bound)
                findings.append(
                    Finding(
                        "pinned-at-bound",
                        f"'{name}' of {holder} reached its bound {bound:g} on turn "
                        f"{reached + 1} of the holding run and stayed there to the end",
                        scenario.origin,
                    )
                )
    return findings
