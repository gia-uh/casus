"""Per-actor declaration types, built from the scenario so invalid states cannot
be expressed.

The first version of this harness handed the model one loose JSON schema and
validated the result by hand. It still rejected twenty-one per cent of what was
declared, because the model kept emitting well-formed JSON describing impossible
actions: a `supply` with no recipient, a strike at a force identifier, a place
that was not on the map.

None of that is a parsing problem. What fixes it is making those states
unrepresentable: each action type gets its own model carrying exactly the fields
the scenario declares for it, the union is discriminated on `type`, and `place`
and `target` are enums of what `offer` allows this actor this turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model

from .state import Action

if TYPE_CHECKING:
    from .scenario import Scenario

MAX_ACTIONS_PER_TURN = 3

#: Extra fields are refused rather than dropped. Pydantic's default is to ignore
#: them, which silently accepted `{"type": "statement", "region": "global"}`.
#: Refusing also emits `additionalProperties: false`, which strict structured
#: output requires. Choices always carry an `enum`, even a single one, which
#: pydantic would otherwise render as a bare `const`.
STRICT = ConfigDict(extra="forbid")


def describe(spec: dict[str, Any], language: str) -> str:
    """An action's description in the scenario's language, English as fallback."""
    description = spec.get("description", "")
    if isinstance(description, dict):
        return str(description.get(language) or description.get("en") or "")
    return str(description)


def _action_model(
    action_type: str,
    spec: dict[str, Any],
    places: tuple[str, ...],
    others: tuple[str, ...],
    language: str,
) -> type[BaseModel]:
    fields: dict[str, Any] = {"type": (Literal[action_type], ...)}
    uses = spec.get("fields") or ()
    if "place" in uses:
        fields["place"] = (
            Literal[places],  # type: ignore[valid-type]
            Field(
                description="one of the place identifiers you can reach",
                json_schema_extra={"enum": list(places)},
            ),
        )
    if "target" in uses:
        fields["target"] = (
            Literal[others],  # type: ignore[valid-type]
            Field(
                description="the other actor this is aimed at",
                json_schema_extra={"enum": list(others)},
            ),
        )
    if "intensity" in uses:
        lo, hi = spec.get("intensity", (1, 3))
        fields["intensity"] = (
            int,
            Field(default=int(lo), ge=int(lo), le=int(hi), description="how hard, low to high"),
        )
    if "entities" in uses:
        fields["entities"] = (
            list[str],
            Field(default_factory=list, description="identifiers of your own units"),
        )
    model = create_model(action_type.title().replace("_", ""), __config__=STRICT, **fields)
    model.__doc__ = describe(spec, language)
    return model


def declaration_model(
    actor: str, offered: dict[str, tuple[str, ...] | None], scenario: Scenario
) -> type[BaseModel]:
    """The type `actor` may speak this turn: one branch per offered action type."""
    if not offered:
        raise ValueError(f"{actor} has nothing to declare, which should never happen")
    declared = scenario.actions
    unknown = sorted(set(offered) - set(declared))
    if unknown:
        raise ValueError(f"offer names action types the scenario never declared: {unknown}")

    all_places = tuple(scenario.data["places"])
    others = tuple(a for a in scenario.actors if a != actor) or scenario.actors
    branches = [
        _action_model(
            action_type,
            declared[action_type],
            tuple(places) if places else all_places,
            others,
            scenario.language(),
        )
        for action_type, places in sorted(offered.items())
    ]
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
                place=data.get("place"),
                target=data.get("target"),
                entities=tuple(data.get("entities") or ()),
                intensity=int(data.get("intensity", 1)),
            )
        )
    return tuple(out)
