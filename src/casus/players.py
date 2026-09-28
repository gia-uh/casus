"""One language model per actor, speaking a type it cannot misuse.

There is no LLM plumbing here: `lingo` owns the transport, the structured call
and the parsing. casus owns the prompt, the type, and what the answer means.

What an actor sees comes from the scenario: its `view` hook turns a throwaway
copy of the world into what the actor believes, its `offer` hook says what the
actor may declare, and the `display` block says how to show the numbers.
"""

from __future__ import annotations

import dataclasses
import random

from lingo import Context, Engine, Message

from . import display
from .actions import MAX_ACTIONS_PER_TURN, declaration_model, describe, to_actions
from .proxy import State
from .resolver import RuleFailed
from .scenario import Scenario
from .state import Action, WorldState

SYSTEM_PROMPT = (
    "You are the national command authority of one state in a strategic crisis "
    "simulation used for teaching. You decide policy, not arithmetic: an external "
    "resolver computes every material outcome, so do not reason about how much "
    "damage you will do. Argue for your choice in `rationale` in at most four "
    "sentences, and state what you believe your opponent will do next in "
    "`assessment`."
)

#: Appended when the scenario is not in English. Field names and action
#: identifiers stay English, because they are a wire format; the prose is read by
#: the room, so it is written in the room's language.
LANGUAGE_NOTE = (
    "Write `rationale` and `assessment` in {language}. Keep the field names and "
    "the action identifiers exactly as given; only the prose is translated."
)

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French"}

Offered = dict[str, tuple[str, ...] | None]


def system_prompt(language: str) -> str:
    if language == "en":
        return SYSTEM_PROMPT
    name = LANGUAGE_NAMES.get(language, language)
    return SYSTEM_PROMPT + " " + LANGUAGE_NOTE.format(language=name)


def offered_actions(scenario: Scenario, world: WorldState, actor: str, rng) -> Offered:
    """What `actor` may declare now: the scenario's `offer`, or everything."""
    if scenario.ruleset.offer is None:
        places = tuple(world.places)
        return {
            t: (places if "place" in (spec.get("fields") or ()) else None)
            for t, spec in scenario.actions.items()
        }
    s = State(world, rng, scenario.resource_bounds(), scenario.attribute_bounds())
    return dict(_hook(scenario.ruleset.offer, "offer", actor, s.read_only("offer")))


def believed(scenario: Scenario, world: WorldState, actor: str, rng) -> WorldState:
    """What `actor` believes the world looks like: the `view` hook on a copy."""
    if scenario.ruleset.view is None:
        return world
    s = State(world, rng, scenario.resource_bounds(), scenario.attribute_bounds()).scratch()
    _hook(scenario.ruleset.view, "view", actor, s)
    # Last turn's events are public, and a fresh working copy starts without them.
    return dataclasses.replace(s.freeze(), events=world.events)


def _hook(fn, kind: str, actor: str, s: State):
    """Run a scenario hook, reporting a failure the way a failing rule is."""
    try:
        return fn(s, actor)
    except Exception as exc:  # a scenario's bug, reported with the hook's name
        raise RuleFailed(
            f"@{kind} '{fn.__name__}' failed for {actor}: {type(exc).__name__}: {exc}"
        ) from exc


@dataclasses.dataclass(frozen=True)
class PlayerTurn:
    actions: tuple[Action, ...]
    rationale: str
    assessment: str
    prompt: str
    declaration: dict
    model: str = ""


@dataclasses.dataclass(frozen=True)
class Player:
    actor_id: str
    scenario: Scenario
    engine: Engine

    @property
    def model(self) -> str:
        return self.scenario.model(self.actor_id)

    def view(self, world: WorldState, rng: random.Random) -> tuple[str, Offered]:
        """What this actor sees, and what it may say.

        Split from `decide` so the random draws happen in a fixed order across
        actors while the calls go out together.
        """
        seen = believed(self.scenario, world, self.actor_id, rng)
        offered = offered_actions(self.scenario, world, self.actor_id, rng)
        return build_prompt(self.actor_id, self.scenario, seen, offered), offered

    async def decide(self, world: WorldState, prompt: str, offered: Offered) -> PlayerTurn:
        schema = declaration_model(self.actor_id, offered, self.scenario)
        context = Context(
            [Message.system(system_prompt(self.scenario.language())), Message.user(prompt)]
        )
        declaration = await self.engine.create(context, schema)
        return PlayerTurn(
            actions=to_actions(declaration, self.actor_id),
            rationale=str(getattr(declaration, "rationale", "")),
            assessment=str(getattr(declaration, "assessment", "")),
            prompt=prompt,
            declaration=declaration.model_dump(),
            model=self.model,
        )


def build_prompt(actor_id: str, scenario: Scenario, view: WorldState, offered: Offered) -> str:
    """Assemble what one actor sees. A string on purpose: it goes in the
    transcript verbatim and the replayer shows it to the audience."""
    me = view.actors[actor_id]
    lines = [
        f"TURN {view.turn}. You are {me.name} ({actor_id}).",
        "",
        "YOUR STANDING ORDERS",
        scenario.briefing(actor_id).strip(),
        "",
        "YOUR POSITION",
    ]
    lines += [
        f"  {display.label(scenario, k)}: {display.shown(scenario, k, v, exact=True)}"
        for k, v in me.resources.items()
    ]
    rung = _rung(scenario, me.resources)
    if rung:
        lines.append(f"  highest rung you have reached: {rung}")

    lines += ["", "YOUR UNITS (exact)"]
    own = [e for e in view.entities if e.owner == actor_id]
    lines += [f"  {_entity_line(scenario, e)}" for e in own] or ["  none"]

    lines += ["", "OTHER ACTORS"]
    for other_id, other in view.actors.items():
        if other_id == actor_id:
            continue
        shown = ", ".join(
            f"{display.label(scenario, k)} {display.shown(scenario, k, other.resources[k], False)}"
            for k in display.standing(scenario)
            if k in other.resources
        )
        rung = _rung(scenario, other.resources)
        lines.append(
            f"  {other.name} ({other_id}): {shown}" + (f", highest rung {rung}" if rung else "")
        )

    lines += ["", "UNITS YOU CAN SEE (estimates)"]
    foreign = [e for e in view.entities if e.owner != actor_id]
    lines += [f"  {_entity_line(scenario, e, estimate=True)}" for e in foreign] or [
        "  none detected"
    ]

    lines += ["", "MAP"]
    for place in view.places.values():
        attrs = display.attributes(scenario, place.attrs)
        lines.append(
            f"  {place.id} ({place.name}): held by {place.owner or 'nobody'}"
            + (f", {attrs}" if attrs else "")
            + (f", adjacent to {', '.join(place.adjacency)}" if place.adjacency else "")
        )

    if view.events:
        lines += ["", "WHAT HAPPENED LAST TURN"]
        lines += [f"  {_event_line(e)}" for e in view.events]

    lines += ["", "ACTIONS AVAILABLE TO YOU THIS TURN"]
    for action_type, places in sorted(offered.items()):
        description = describe(scenario.actions.get(action_type, {}), scenario.language())
        where = f" Can reach: {', '.join(places) if places else 'nowhere'}." if places else ""
        lines.append(f"  {action_type} — {description}{where}")

    lines += [
        "",
        (
            f"Declare between 1 and {MAX_ACTIONS_PER_TURN} actions. Each action type "
            "carries only the fields it uses. Aiming an action at a place it cannot "
            "reach wastes the turn."
        ),
    ]
    return "\n".join(lines)


def _rung(scenario: Scenario, resources: dict[str, float]) -> str | None:
    resource = (scenario.display.get("ladder") or {}).get("resource")
    if not resource or resource not in resources:
        return None
    value = int(resources[resource])
    name = display.rung_label(scenario, value)
    return f"{value} ({name})" if name else str(value)


def _entity_line(scenario: Scenario, entity, estimate: bool = False) -> str:
    attrs = ", ".join(
        f"{k} {v:.0f}"
        if isinstance(v, float) and k == "strength"
        else f"{k} {display.number(v)}"
        for k, v in entity.attrs.items()
        if k not in display.hidden(scenario)
    )
    tail = " (estimate)" if estimate else ""
    return (
        f"{entity.id}: {entity.kind} in {entity.place}" + (f", {attrs}" if attrs else "") + tail
    )


def _event_line(event) -> str:
    d = event.detail
    who = f"{d['actor']}: " if d.get("actor") else ""
    where = f" [{d['place']}]" if d.get("place") else ""
    reason = f" — {d['reason']}" if d.get("reason") else ""
    return f"{who}{event.id}{where}{reason}"
