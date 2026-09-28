"""The news ticker: a short public account of each turn, read-only by construction.

It is a separate module for one reason: `test_narrator_cannot_mutate_state`. The
moment a model is allowed to adjust a number for narrative reasons, every figure
in the run stops being auditable.

**The model does not write the subject.** It is given the facts of the turn, in
order, and returns one predicate per fact; the engine puts the actor in front,
taken from the event's `actor`. Letting the model name the actor produced three
misattributions in twelve dispatches, and an enum on an `actor` field did not
help, because the enum stops it inventing a country and not choosing the wrong
one. Pairing positionally removes the choice.
"""

from __future__ import annotations

import functools

from lingo import Context, Engine, Message
from pydantic import ConfigDict, Field, create_model

from . import display
from .scenario import Scenario
from .state import Event, WorldState

SYSTEM_PROMPT = (
    "You are a wire-service correspondent covering an international crisis. You "
    "are given the verified facts of the last twenty-four hours, numbered. For "
    "each fact, in the same order, write the predicate of one short past-tense "
    "sentence — what happened — WITHOUT naming the actor and without a subject, "
    "because the subject is added for you. Example: for a fact about a fuel "
    "transfer, write 'transferred ten days of fuel to Cuba', not 'Russia "
    "transferred ten days of fuel to Cuba'. Report only what you are given: no "
    "speculation, no invented numbers, no quotations."
)

#: Facts reported per turn. A resolver can emit two dozen events in a heavy
#: turn, and a wire dispatch is not a log.
MAX_FACTS = 5

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French"}


@functools.lru_cache(maxsize=16)
def dispatch_model(count: int) -> type:
    """Exactly `count` predicates, so fact *i* and predicate *i* are the same event.

    The length is pinned at both ends: four predicates for five facts would shift
    every subject by one, and it would look plausible on screen.
    """
    model = create_model(
        "Dispatch",
        __config__=ConfigDict(extra="forbid"),
        predicates=(
            list[str],
            Field(
                min_length=count,
                max_length=count,
                description="one predicate per numbered fact, in the same order",
            ),
        ),
    )
    model.__doc__ = "The day's wire dispatch: one predicate per fact, in order."
    return model


def reportable(events: list[Event], scenario: Scenario) -> list[Event]:
    unreported = set(scenario.display.get("unreported") or ())
    return [e for e in events if e.id not in unreported][:MAX_FACTS]


async def narrate(
    world: WorldState, events: list[Event], engine: Engine, scenario: Scenario
) -> str:
    """Return a short public account of the turn that just resolved."""
    facts = reportable(events, scenario)
    if not facts:
        return ""

    prompt = build_prompt(world, facts, scenario)
    context = Context([Message.system(SYSTEM_PROMPT), Message.user(prompt)])
    dispatch = await engine.create(context, dispatch_model(len(facts)))

    names = {a.id: a.name for a in world.actors.values()}
    lines = []
    for fact, predicate in zip(facts, dispatch.predicates, strict=True):
        text = " ".join(str(predicate).split())
        if not text:
            continue
        subject = names.get(fact.detail.get("actor") or "", "")
        sentence = f"{subject} {text}".strip() if subject else text
        lines.append(sentence if sentence.endswith((".", "!", "?")) else sentence + ".")
    return " ".join(lines)


def build_prompt(world: WorldState, facts: list[Event], scenario: Scenario) -> str:
    lines = [f"DAY {world.turn - 1}. Verified facts, numbered:", ""]
    for index, fact in enumerate(facts, start=1):
        place = fact.detail.get("place")
        where = f" in {place}" if place else ""
        lines.append(f"  {index}. [{fact.id}]{where}: {fact.detail.get('reason', '')}")

    lines += ["", "Standing position at the end of the day:"]
    for actor in world.actors.values():
        shown = ", ".join(
            f"{display.label(scenario, k)} {display.number(actor.resources[k])}"
            for k in display.standing(scenario)
            if k in actor.resources
        )
        lines.append(f"  {actor.name}: {shown}")
    for place in world.places.values():
        attrs = display.attributes(scenario, place.attrs)
        lines.append(
            f"  {place.name}: held by {place.owner or 'nobody'}"
            + (f", {attrs}" if attrs else "")
        )

    lines += [
        "",
        (
            f"Write exactly {len(facts)} predicates, one per numbered fact, in "
            "order. No subject, no actor name — the subject is added for you."
        ),
    ]
    language = scenario.language()
    if language != "en":
        # At the end of the user message, not only in the system prompt: the facts
        # are English, and a correspondent given English facts and a distant
        # instruction drifted back into English in one dispatch of twelve.
        lines.append(
            f"Write them in {LANGUAGE_NAMES.get(language, language)}, "
            "including place names where they have a common form in that language."
        )
    return "\n".join(lines)
