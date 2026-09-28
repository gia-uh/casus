"""Per-scenario declaration types, built so invalid states cannot be expressed.

The first version of this harness handed the model one loose JSON schema with a
free-form `type`, `region` and `target_actor`, then validated the result by hand.
Schema failures were zero and it still rejected twenty-one per cent of everything
declared, because the model kept emitting well-formed JSON describing impossible
actions: a `supply` with no recipient, a strike at a force identifier, a region
that was not on the map.

None of that is a parsing problem, so no amount of better parsing fixes it. What
fixes it is making those states unrepresentable. Each action type gets its own
model carrying exactly the fields it uses; the union is discriminated on `type`;
and `region` and `target_actor` are `Literal` enums built from the scenario in
hand. A model choosing from this cannot ask to supply nobody, and cannot name a
region that does not exist.
"""

from __future__ import annotations

import functools
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model

from .v1.state import ACTION_TYPES, Action

MAX_ACTIONS_PER_TURN = 3

#: Extra fields are refused rather than dropped. Pydantic's default is to ignore
#: them, which silently accepted `{"type": "statement", "region": "global"}` —
#: the exact thing both models kept doing. Refusing also emits
#: `additionalProperties: false`, which strict structured output requires.
STRICT = ConfigDict(extra="forbid")

#: What each action type actually uses. `region` and `target` say which
#: scenario-bound enum the field draws from; everything else is fixed.
#:
#: This table is the single place the vocabulary is described. `rules.py` decides
#: whether a declared action is *legal*; this decides whether it is even
#: *sayable*, and the two must not drift — `test_actions.py` asserts they agree.
FIELDS: dict[str, tuple[str, ...]] = {
    "hold": (),
    "statement": (),
    "negotiate": ("target",),
    "concede": ("target",),
    "sanction": ("target",),
    "supply": ("target",),
    "mobilize": ("region",),
    "deploy": ("region", "forces"),
    "disperse": ("region",),
    "harden": ("region",),
    "blockade": ("region", "intensity"),
    "cyber": ("region", "intensity"),
    "covert": ("region", "intensity"),
    "strike": ("region", "intensity"),
    "air_campaign": ("region", "intensity"),
    "invade": ("region", "intensity"),
}

DESCRIPTIONS: dict[str, str] = {
    "hold": "Take no action this turn.",
    "statement": "Make a public declaration. Costs nothing and commits nothing.",
    "negotiate": "Open or continue talks with another actor.",
    "concede": "Give ground to another actor to defuse the crisis.",
    "sanction": "Impose economic measures on another actor.",
    "supply": "Transfer fuel to another actor. Names the actor, never a region.",
    "mobilize": "Call up reserves into a region where you already have ground forces.",
    "deploy": "Move named forces of yours into a region.",
    "disperse": "Spread your forces out: harder to hit, weaker in attack.",
    "harden": "Dig your forces in: much harder to hit, much weaker in attack.",
    "blockade": "Interdict shipping in a sea zone.",
    "cyber": "Attack an adversary's networks in a region.",
    "covert": "Act clandestinely in a region.",
    "strike": "Hit a region with air or naval platforms.",
    "air_campaign": "Sustained air operations against a region.",
    "invade": "Put ground forces into a region to take it.",
}


def _action_model(
    action_type: str, regions: tuple[str, ...], others: tuple[str, ...]
) -> type[BaseModel]:
    fields: dict[str, tuple] = {"type": (Literal[action_type], ...)}
    uses = FIELDS[action_type]
    if "region" in uses:
        fields["region"] = (
            Literal[regions],  # type: ignore[valid-type]
            Field(description="one of the region identifiers on the map"),
        )
    if "target" in uses:
        fields["target_actor"] = (
            Literal[others],  # type: ignore[valid-type]
            Field(description="the other actor this is aimed at"),
        )
    if "intensity" in uses:
        fields["intensity"] = (
            int,
            Field(default=1, ge=1, le=3, description="1 probing, 2 sustained, 3 maximum"),
        )
    if "forces" in uses:
        fields["forces"] = (
            list[str],
            Field(default_factory=list, description="identifiers of your own forces to move"),
        )
    model = create_model(action_type.title().replace("_", ""), __config__=STRICT, **fields)
    model.__doc__ = DESCRIPTIONS[action_type]
    return model


@functools.lru_cache(maxsize=128)
def declaration_model(
    actor: str,
    legal: tuple[str, ...],
    regions: tuple[str, ...],
    actors: tuple[str, ...],
) -> type[BaseModel]:
    """The type `actor` may speak this turn.

    Cached on its arguments because the shape only changes when the legal action
    set or the map does, and building a discriminated union is not free.
    """
    if not legal:
        raise ValueError(f"{actor} has no legal actions, which should never happen")
    others = tuple(a for a in actors if a != actor) or actors
    branches = [_action_model(t, regions, others) for t in legal]
    union = (
        Annotated[Union[tuple(branches)], Field(discriminator="type")]  # noqa: UP007
        if len(branches) > 1
        else branches[0]
    )
    declaration = create_model(
        "Declaration",
        __config__=STRICT,
        actions=(
            list[union],  # type: ignore[valid-type]
            Field(min_length=1, max_length=MAX_ACTIONS_PER_TURN),
        ),
        rationale=(str, Field(description="why, in at most four sentences")),
        assessment=(str, Field(description="what you expect your opponent to do next")),
    )
    declaration.__doc__ = (
        "Your declaration for this turn: what you will do, why, and what you expect in return."
    )
    return declaration


def to_actions(declaration: BaseModel, actor: str) -> tuple[Action, ...]:
    """Convert a validated declaration into the engine's own `Action` records."""
    out = []
    for item in declaration.actions:  # type: ignore[attr-defined]
        data = item.model_dump()
        out.append(
            Action(
                actor=actor,
                type=data["type"],
                region=data.get("region"),
                target_actor=data.get("target_actor"),
                forces=tuple(data.get("forces") or ()),
                intensity=int(data.get("intensity", 1)),
            )
        )
    return tuple(out)


def vocabulary_matches_the_engine() -> bool:
    """`FIELDS` and `DESCRIPTIONS` have to cover exactly what `state.py` allows."""
    return set(FIELDS) == set(ACTION_TYPES) == set(DESCRIPTIONS)
