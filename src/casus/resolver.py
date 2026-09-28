"""The resolver: one turn, five phases, in a fixed order.

    legality → upkeep → movement → contest → consequences

A scenario puts rules in phases; it does not choose the order. The order is what
makes "what has happened so far this turn" exact: a rule sees the events emitted
by earlier phases and earlier rules, and nothing else.

Before any rule runs, the resolver puts the actions in a canonical order, clamps
intensity into each action's declared bounds, drops a place from an action that
takes none, and rejects what no scenario could accept: an undeclared action
type, an unknown actor, place or target.

A rule that raises abandons the whole turn. The input state is never touched,
so there is no half-applied turn to write down.

This module performs no I/O and makes no model call.
"""

from __future__ import annotations

import dataclasses
import random
from typing import Any

from .proxy import ActionView, Mutation, State
from .ruleset import PHASES, RuleSet
from .state import Action, Event, WorldState


class RuleFailed(RuntimeError):
    """A scenario rule raised. The turn was abandoned."""


def canonical_order(actions: list[Action]) -> list[Action]:
    """Sort so a turn resolves identically however the declarations arrived."""
    return sorted(actions, key=lambda a: (a.actor, a.type, a.place or "", a.target or ""))


def normalise(action: Action, declared: dict[str, dict[str, Any]]) -> Action:
    spec = declared.get(action.type)
    if spec is None:
        return action
    fields = spec.get("fields") or ()
    place = action.place if "place" in fields else None
    intensity = action.intensity
    if "intensity" in spec:
        lo, hi = spec["intensity"]
        intensity = max(int(lo), min(int(hi), intensity))
    if place == action.place and intensity == action.intensity:
        return action
    return dataclasses.replace(action, place=place, intensity=intensity)


def _engine_rejection(world: WorldState, action: Action, declared: dict) -> str | None:
    if action.type not in declared:
        return f"unknown action type '{action.type}'"
    if action.actor not in world.actors:
        return f"unknown actor '{action.actor}'"
    if action.place is not None and action.place not in world.places:
        return f"unknown place '{action.place}'"
    if action.target is not None and action.target not in world.actors:
        return f"unknown target actor '{action.target}'"
    return None


def resolve(
    world: WorldState,
    actions: list[Action],
    ruleset: RuleSet,
    rng: random.Random,
    declared: dict[str, dict[str, Any]],
    resource_bounds: dict[str, tuple[float, float]] | None = None,
    attribute_bounds: dict[str, tuple[float, float]] | None = None,
) -> tuple[WorldState, list[Event], list[Mutation]]:
    """Advance the world by one turn. Pure, and deterministic given `rng`."""
    s = State(world, rng, resource_bounds, attribute_bounds)
    views = [
        ActionView.of(normalise(a, declared), declared) for a in canonical_order(list(actions))
    ]
    s.set_actions(views)

    for view in views:
        reason = _engine_rejection(world, view, declared)
        if reason is not None:
            with s.attributing(rule="engine", phase="legality", action=view):
                s.reject(reason)

    for phase in PHASES:
        for r in ruleset.for_phase(phase):
            if r.on is None:
                _invoke(s, r, phase, None)
                continue
            for action in s.actions:
                if action.type not in r.on or s.rejected(action):
                    continue
                _invoke(s, r, phase, action)

    s.turn = world.turn + 1
    return s.freeze(), s.events, s.ledger


def _invoke(s: State, r, phase: str, action: ActionView | None) -> None:
    try:
        with s.attributing(rule=r.name, phase=phase, action=action):
            if action is None:
                r.fn(s)
            else:
                r.fn(s, action)
    except Exception as exc:  # a scenario's bug, reported with its rule's name
        raise RuleFailed(
            f"rule '{r.name}' failed in {phase}: {type(exc).__name__}: {exc}"
        ) from exc
