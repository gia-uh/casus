"""Shared state builders.

Every helper here builds state from the module's own constants rather than from
literals repeated in the assertions, so a test cannot pass by agreeing with
itself.
"""

from __future__ import annotations

from casus.v1.state import ActorState, Force, RegionState, WorldState


def make_actor(actor_id: str, **overrides) -> ActorState:
    base = dict(
        id=actor_id,
        name=actor_id,
        fuel_days=60.0,
        munitions=80.0,
        political_capital=70.0,
        domestic_support=70.0,
        intl_legitimacy=60.0,
        isr=0.8,
        fuel_inflow=4.0,
        escalation_rung=0,
    )
    base.update(overrides)
    return ActorState(**base)


def make_region(region_id: str, owner: str, **overrides) -> RegionState:
    base = dict(
        id=region_id,
        name=region_id,
        owner=owner,
        adjacency=(),
        centroid=(23.1, -82.4),
        control=100.0,
        infrastructure=100.0,
        civilian_distress=0.0,
        population=1_000_000,
        terrain="coastal",
        country=owner,
    )
    base.update(overrides)
    return RegionState(**base)


def make_force(owner: str, kind: str, **overrides) -> Force:
    base = dict(
        id=f"{owner}-{kind}-1",
        owner=owner,
        kind=kind,
        strength=50.0,
        readiness=0.9,
        region="r1",
        posture="garrison",
    )
    base.update(overrides)
    return Force(**base)


def make_world(
    actors: dict[str, ActorState] | None = None,
    regions: dict[str, RegionState] | None = None,
    forces: tuple[Force, ...] = (),
    turn: int = 1,
    relations: dict[str, int] | None = None,
) -> WorldState:
    actors = actors or {"ATK": make_actor("ATK"), "DEF": make_actor("DEF")}
    regions = regions or {
        "r1": make_region("r1", "DEF"),
        "sea-1": make_region("sea-1", "", terrain="sea", population=0),
    }
    return WorldState(
        turn=turn,
        actors=actors,
        regions=regions,
        forces=forces,
        relations=relations or {"ATK>DEF": -60, "DEF>ATK": -60},
    )


class FakeEngine:
    """Stands in for a lingo Engine in tests.

    Validates a canned payload against whatever schema the caller asks for, so a
    test that hands it an impossible declaration fails the same way the real
    provider would, rather than sliding through.
    """

    def __init__(self, reply=None):
        self.reply = (
            reply
            if reply is not None
            else {
                "actions": [{"type": "hold"}],
                "rationale": "wait",
                "assessment": "they wait too",
            }
        )
        self.prompts: list[str] = []
        self.schemas: list[type] = []

    async def create(self, context, schema, *instructions):
        prompt = context.messages[-1].content
        self.prompts.append(prompt)
        self.schemas.append(schema)
        payload = self.reply(prompt) if callable(self.reply) else self.reply
        return schema.model_validate(payload)


def scripted(per_actor: dict[str, dict] | None = None, default: dict | None = None):
    """A reply function keyed on the actor named in the prompt."""
    per_actor = per_actor or {}
    fallback = default or {
        "actions": [{"type": "hold"}],
        "rationale": "wait",
        "assessment": "nothing",
    }

    def reply(prompt: str) -> dict:
        actor = prompt.split("You are ")[1].split("(")[1].split(")")[0]
        return per_actor.get(actor, fallback)

    return reply
