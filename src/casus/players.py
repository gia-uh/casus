"""One language model per actor, speaking a type it cannot misuse.

There is no LLM plumbing in this package. `lingo` owns the transport, the
structured-output call and the parsing; casus owns the prompt, the type, and what
the answer means. A model that returns something unusable is a lingo bug, and it
gets fixed in lingo.

What casus does own is the shape of what may be said. `actions.declaration_model`
builds a discriminated union bound to this scenario's regions and actors, so a
declaration that names a region off the map, or supplies nobody, cannot be
constructed at all: the provider enforces the enum and lingo validates the
result.
"""

from __future__ import annotations

import dataclasses
import random

from lingo import Context, Engine, Message

from .v1 import rules
from .v1.actions import MAX_ACTIONS_PER_TURN, declaration_model, to_actions
from .v1.state import RUNG_NAMES, Action, WorldState

SYSTEM_PROMPT = (
    "You are the national command authority of one state in a strategic crisis "
    "simulation used for teaching. You decide policy, not arithmetic: an external "
    "resolver computes every material outcome, so do not reason about how much "
    "damage you will do. Argue for your choice in `rationale` in at most four "
    "sentences, and state what you believe your opponent will do next in "
    "`assessment`."
)

#: Appended when the scenario is not in English. The field names stay English —
#: they are a wire format, not prose — but everything the model writes is read by
#: the room, so it is written in the room's language.
LANGUAGE_NOTE = (
    "Write `rationale` and `assessment` in {language}. Keep the field names and "
    "the action identifiers exactly as given; only the prose is translated."
)

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French"}


def system_prompt(language: str) -> str:
    if language == "en":
        return SYSTEM_PROMPT
    name = LANGUAGE_NAMES.get(language, language)
    return SYSTEM_PROMPT + " " + LANGUAGE_NOTE.format(language=name)


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
    briefing: str
    model: str
    engine: Engine
    language: str = "en"

    def view(self, state: WorldState, rng: random.Random) -> tuple[str, tuple[str, ...]]:
        """What this actor sees, and what it may say.

        Split out from `decide` so the random draws happen in a fixed order across
        actors while the calls themselves go out together. Determinism lives here;
        concurrency lives in the caller.
        """
        seen = rules.perturb_view(state, self.actor_id, rng)
        legal = rules.legal_action_types(state, self.actor_id)
        return build_prompt(self.actor_id, self.briefing, seen, legal), legal

    async def decide(
        self, state: WorldState, prompt: str, legal: tuple[str, ...]
    ) -> PlayerTurn:
        schema = declaration_model(
            self.actor_id, legal, tuple(state.regions), tuple(sorted(state.actors))
        )
        context = Context([Message.system(system_prompt(self.language)), Message.user(prompt)])
        declaration = await self.engine.create(context, schema)
        return PlayerTurn(
            actions=to_actions(declaration, self.actor_id),
            rationale=str(getattr(declaration, "rationale", "")),
            assessment=str(getattr(declaration, "assessment", "")),
            prompt=prompt,
            declaration=declaration.model_dump(),
            model=self.model,
        )


def build_prompt(actor_id: str, briefing: str, view: WorldState, legal: tuple[str, ...]) -> str:
    """Assemble what one actor sees. Returned as a string on purpose: it goes in
    the transcript verbatim and the replayer shows it to the audience."""
    me = view.actors[actor_id]
    lines = [
        f"TURN {view.turn}. You are {me.name} ({actor_id}).",
        "",
        "YOUR STANDING ORDERS",
        briefing.strip(),
        "",
        "YOUR POSITION",
        f"  sustainment: {me.fuel_days:.0f} fuel-days ({_fuel_band(me.fuel_days)})",
        f"  munitions {me.munitions:.0f}/100 · political capital {me.political_capital:.0f}/100",
        (
            f"  domestic support {me.domestic_support:.0f}/100 · "
            f"international legitimacy {me.intl_legitimacy:.0f}/100"
        ),
        f"  intelligence quality: {_isr_band(me.isr)}",
        (
            "  reserves you can still call up: "
            f"{me.reserve_pool * rules.TROOPS_PER_STRENGTH_POINT:,.0f} personnel"
        ),
        (
            f"  highest rung you have reached: {me.escalation_rung} "
            f"({RUNG_NAMES[me.escalation_rung]})"
        ),
        "",
        "YOUR FORCES (exact)",
    ]
    lines += [f"  {_force_line(f)}" for f in view.forces_of(actor_id)] or ["  none"]

    lines += ["", "OTHER ACTORS"]
    for other_id, other in view.actors.items():
        if other_id == actor_id:
            continue
        lines.append(
            f"  {other.name} ({other_id}): sustainment {_fuel_band(other.fuel_days)}, "
            f"legitimacy {_band(other.intl_legitimacy)}, "
            f"highest rung {other.escalation_rung} ({RUNG_NAMES[other.escalation_rung]})"
        )

    lines += ["", f"FORCES YOU CAN SEE (estimates — your intelligence is {_isr_band(me.isr)})"]
    foreign = [f for f in view.forces if f.owner != actor_id]
    lines += [f"  {_force_line(f)} (estimate)" for f in foreign] or ["  none detected"]

    lines += ["", "MAP"]
    for region in view.regions.values():
        holder = region.owner or "unclaimed"
        lines.append(
            f"  {region.id} ({region.name}, {region.terrain}, pop {region.population:,}): "
            f"held by {holder}, control {region.control:.0f}%, "
            f"infrastructure {region.infrastructure:.0f}%, "
            f"civilian distress {region.civilian_distress:.0f}%"
            + (f", adjacent to {', '.join(region.adjacency)}" if region.adjacency else "")
        )

    if view.log:
        lines += ["", "WHAT HAPPENED LAST TURN"]
        lines += [f"  {_resolution_line(r)}" for r in view.log]

    lines += ["", "ACTIONS AVAILABLE TO YOU THIS TURN", "  " + ", ".join(legal)]
    for action_type in legal:
        if action_type not in rules.DELIVERY_KINDS:
            continue
        reach = rules.reachable_regions(view, actor_id, action_type)
        lines.append(
            f"  {action_type} can reach: "
            + (", ".join(reach) if reach else "nowhere right now")
        )

    lines += [
        "",
        (
            f"Declare between 1 and {MAX_ACTIONS_PER_TURN} actions. Each action type "
            "carries only the fields it uses: a supply names an actor, a strike names a "
            "region. Aiming an action at a region it cannot reach wastes the turn."
        ),
    ]
    return "\n".join(lines)


def _force_line(force) -> str:
    return (
        f"{force.id}: {force.kind} strength {force.strength:.0f} in {force.region}, "
        f"posture {force.posture}, readiness {force.readiness:.0%}"
    )


def _resolution_line(resolution) -> str:
    where = f" [{resolution.region}]" if resolution.region else ""
    who = f"{resolution.actor}: " if resolution.actor else ""
    return f"{who}{resolution.kind}{where} — {resolution.reason}"


def _fuel_band(days: float) -> str:
    if days <= 0:
        return "exhausted"
    if days < 15:
        return "critical"
    if days < 45:
        return "strained"
    return "sufficient"


def _isr_band(isr: float) -> str:
    if isr >= 0.8:
        return "excellent"
    if isr >= 0.5:
        return "adequate"
    if isr >= 0.25:
        return "poor"
    return "very poor"


def _band(value: float) -> str:
    if value >= 70:
        return "high"
    if value >= 40:
        return "moderate"
    return "low"
