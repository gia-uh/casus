"""v1's physics tests, pointed at the reference ruleset.

The tests in this directory were written against v1's `rules.resolve(world,
actions, rng)`. This module offers that same call, and v1's helpers
(`legal_action_types`, `perturb_view`, `occupation_requirement`), but behind
them it converts the world into the new state, runs the reference ruleset
through the resolver and the proxy, and converts the result back. The
constants come from the reference ruleset's module.

So the test bodies are v1's unchanged, and what they check is the port.
"""

from __future__ import annotations

import pathlib
import random

from v1shape import (
    Action,
    ActorState,
    Force,
    RegionState,
    Resolution,
    WorldState,
)

from casus import resolver
from casus.proxy import State
from casus.scenario import Scenario
from casus.state import Action as Action2
from casus.state import Actor, Entity, Place
from casus.state import WorldState as World2

REFERENCE = Scenario.load(pathlib.Path(__file__).parents[2] / "scenarios" / "reference")
MODULE = REFERENCE.module

ACTOR_FIELDS = (
    "fuel_days", "fuel_inflow", "munitions", "political_capital", "domestic_support",
    "intl_legitimacy", "isr", "reserve_pool", "escalation_rung",
)  # fmt: skip


def to_v2(world: WorldState) -> World2:
    return World2(
        turn=world.turn,
        actors={
            a: Actor(id=a, name=s.name, resources={k: getattr(s, k) for k in ACTOR_FIELDS})
            for a, s in world.actors.items()
        },
        places={
            r: Place(
                id=r,
                name=g.name,
                owner=g.owner,
                adjacency=tuple(g.adjacency),
                attrs={
                    "control": g.control,
                    "infrastructure": g.infrastructure,
                    "civilian_distress": g.civilian_distress,
                    "population": g.population,
                    "terrain": g.terrain,
                    "country": g.country,
                    "lat": g.centroid[0],
                    "lon": g.centroid[1],
                },
            )
            for r, g in world.regions.items()
        },
        entities=tuple(
            Entity(
                id=f.id,
                owner=f.owner,
                kind=f.kind,
                place=f.region,
                attrs={"strength": f.strength, "readiness": f.readiness, "posture": f.posture},
            )
            for f in world.forces
        ),
    )


def to_resolution(event) -> Resolution:
    d = dict(event.detail)
    return Resolution(
        kind=event.id,
        actor=d.pop("actor", None),
        region=d.pop("place", None),
        reason=d.pop("reason", ""),
        detail=d,
    )


def to_v1(world: World2, relations: dict[str, int]) -> WorldState:
    return WorldState(
        turn=world.turn,
        actors={
            a: ActorState(
                id=a,
                name=actor.name,
                **{k: v for k, v in actor.resources.items() if k != "escalation_rung"},
                escalation_rung=int(actor.resources["escalation_rung"]),
            )
            for a, actor in world.actors.items()
        },
        regions={
            p: RegionState(
                id=p,
                name=place.name,
                owner=place.owner,
                adjacency=tuple(place.adjacency),
                centroid=(place.attrs["lat"], place.attrs["lon"]),
                control=place.attrs["control"],
                infrastructure=place.attrs["infrastructure"],
                civilian_distress=place.attrs["civilian_distress"],
                population=int(place.attrs["population"]),
                terrain=place.attrs["terrain"],
                country=place.attrs["country"],
            )
            for p, place in world.places.items()
        },
        forces=tuple(
            Force(
                id=e.id,
                owner=e.owner,
                kind=e.kind,
                strength=e.attrs["strength"],
                readiness=e.attrs["readiness"],
                region=e.place,
                posture=e.attrs["posture"],
            )
            for e in world.entities
        ),
        relations=dict(relations),
        log=tuple(to_resolution(e) for e in world.events),
    )


def to_action(action: Action) -> Action2:
    return Action2(
        actor=action.actor,
        type=action.type,
        place=action.region,
        target=action.target_actor,
        entities=tuple(action.forces),
        intensity=action.intensity,
    )


def _state(world: WorldState, rng: random.Random) -> State:
    return State(to_v2(world), rng, REFERENCE.resource_bounds(), REFERENCE.attribute_bounds())


class _Rules:
    """v1's `rules` module, as far as its tests use it."""

    def resolve(self, world: WorldState, actions: list[Action], rng: random.Random):
        new, events, _ = resolver.resolve(
            to_v2(world),
            [to_action(a) for a in actions],
            REFERENCE.ruleset,
            rng,
            REFERENCE.actions,
            REFERENCE.resource_bounds(),
            REFERENCE.attribute_bounds(),
        )
        return to_v1(new, world.relations), [to_resolution(e) for e in events]

    def legal_action_types(self, world: WorldState, actor: str) -> tuple[str, ...]:
        offered = REFERENCE.ruleset.offer(_state(world, random.Random(0)).read_only("offer"), actor)
        return tuple(sorted(offered))

    def reachable_regions(self, world: WorldState, actor: str, action_type: str):
        offered = REFERENCE.ruleset.offer(_state(world, random.Random(0)).read_only("offer"), actor)
        return tuple(offered.get(action_type) or ())

    def perturb_view(self, world: WorldState, actor: str, rng: random.Random) -> WorldState:
        seen = _state(world, rng).scratch()
        REFERENCE.ruleset.view(seen, actor)
        return to_v1(seen.freeze(), world.relations)

    def _air_defence_divisor(self, forces) -> float:
        return MODULE._air_defence_divisor(
            sum(f.strength for f in forces if f.kind == "air_defense")
        )

    @property
    def ESCALATION_RUNGS(self) -> dict[str, int]:
        return {t: spec["rung"] for t, spec in REFERENCE.actions.items()}

    def __getattr__(self, name: str):
        return getattr(MODULE, name)


rules = _Rules()
